# AI Document Validation Pipeline — Architecture

Automated document verification that runs on every provider onboarding submission before a human reviewer sees the application. Non-blocking by design: every failure path falls back gracefully so the onboarding queue never stalls.

> **Two AI pipelines in this codebase:**
> - **This document** — `apps/provider/ai_validation.py` — validates onboarding documents (vision models, Celery background task, advisory result for staff).
> - **Recommendation pipeline** — `apps/booking/ai_recommendation.py` — generates one-sentence provider match reasons at booking time (inline, synchronous, returns immediately). Same multi-provider registry and fallback pattern; controlled by `AI_RECOMMENDATION_ENABLED` and `AI_RECOMMENDATION_PROVIDER` in Constance.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Trigger & Entry Point](#2-trigger--entry-point)
3. [Celery Task](#3-celery-task)
4. [Core Validation Logic](#4-core-validation-logic)
5. [AI Provider Adapters](#5-ai-provider-adapters)
6. [Prompt Design](#6-prompt-design)
7. [Result Scoring](#7-result-scoring)
8. [Fallback Paths](#8-fallback-paths)
9. [Audit Log](#9-audit-log)
10. [Runtime Controls (Constance)](#10-runtime-controls-constance)
11. [Status Flow Diagram](#11-status-flow-diagram)
12. [Data Flow: End to End](#12-data-flow-end-to-end)

---

## 1. Overview

When a provider submits their onboarding application, the API immediately sets the application to `pending` and enqueues a background Celery task. That task calls a vision-capable AI model (or a cascade of models) to inspect the uploaded documents against the applicant's declared identity. The result — `passed`, `flagged`, or `failed` — is written back to the `ProviderOnboarding` row and displayed as an advisory report to the human staff reviewer.

```
Provider submits → API → Celery task → AI provider(s) → report stored → staff reviews
```

The AI result is **advisory only**. Staff make the final approve/reject decision.

---

## 2. Trigger & Entry Point

**File:** `apps/provider/views.py` — `OnboardingSubmitView.post()`

After all required fields are validated, the submit view does two things atomically:

```python
# 1. Advance FSM + reset AI state
onboarding.status = OnboardingStatus.PENDING
onboarding.ai_validation_status = AIValidationStatus.PENDING
onboarding.ai_validation_report = {}
onboarding.save(update_fields=["status", "ai_validation_status", "ai_validation_report"])

# 2. Enqueue task AFTER the DB transaction commits
onboarding_id = str(onboarding.pk)
transaction.on_commit(
    lambda: validate_onboarding_documents.delay(onboarding_id)
)
```

Key design decisions:
- `on_commit` ensures the task is never dispatched for a row that rolled back. Without it, the worker could pick up the task before the row exists.
- Only the UUID string is passed to the task — no ORM objects cross the process boundary, keeping the payload JSON-serialisable and retry-safe.
- `ai_validation_status` is reset to `PENDING` on every submission (including resubmissions after `changes_required`), clearing any previous result.

---

## 3. Celery Task

**File:** `apps/provider/tasks.py` — `validate_onboarding_documents`

```
Task: validate_onboarding_documents
  max_retries: 2  (3 total attempts)
  acks_late: True
  reject_on_worker_lost: True
  retry countdown: 60s, 120s (exponential back-off)
```

**Execution sequence:**

1. Load the `ProviderOnboarding` row from DB. If it no longer exists (deleted), log and return.
2. Set `ai_validation_status = RUNNING` and save — this is visible to staff in the admin.
3. Call `validate_onboarding()` (the core logic in `ai_validation.py`).
4. Map the returned `status` string to `AIValidationStatus` and persist the full report JSON.

**Retry behaviour:**

- `validate_onboarding()` catches all its own errors and always returns a dict — it never raises.
- The outer `try/except` in the task guards against unexpected bugs that slip through.
- If all retries are exhausted, `_mark_flagged()` is called — the application gets `ai_validation_status=FLAGGED` so it still surfaces for manual review instead of silently stalling.

```
attempt 1 fails → retry in 60s
attempt 2 fails → retry in 120s
attempt 3 fails → _mark_flagged() → queue keeps moving
```

---

## 4. Core Validation Logic

**File:** `apps/provider/ai_validation.py` — `validate_onboarding(onboarding)`

This function orchestrates the full pipeline. It never raises — every exception path returns a `"flagged"` fallback dict.

### Step 1 — Feature flag check

```python
if not config.AI_VALIDATION_ENABLED:
    return _BYPASS_RESULT  # status=passed, confidence=1.0
```

`AI_VALIDATION_ENABLED` is a Constance flag togglable live from Django Admin without restarting. Disabling it auto-passes all documents — useful during load testing or when all AI APIs are down.

### Step 2 — Document encoding

Each document file is read from disk and base64-encoded:

```python
doc_labels = {
    "nid_front":        onboarding.nid_front,
    "nid_back":         onboarding.nid_back,
    "police_clearance": onboarding.police_clearance_certificate,
    "professional_cert":onboarding.professional_certificate,  # optional
}
```

`_encode_file()` returns `{"mime": "<type>", "data": "<base64>"}` or `None` if the file is missing or unreadable. If ALL documents are unreadable, an early fallback is returned immediately (no API call).

MIME detection uses `mimetypes.guess_type`. Unknown types are treated as `image/jpeg` so vision models can still attempt to read them.

**Image orientation & size:** image bytes are normalized by `_normalize_image()` before encoding — EXIF orientation is baked into the pixels (`ImageOps.exif_transpose`) and the longest edge is capped at 2000 px, then re-encoded as JPEG. This fixes phone photos whose rotation lives only in an EXIF tag (the model sees raw pixels, not the tag) and trims image tokens. Photos with **no** EXIF tag can still be physically rotated (e.g. a landscape ID card shot in a portrait frame); the model is instructed in the system prompt to mentally rotate and read such images and to never flag orientation itself as a defect. PDFs are passed through untouched.

### Step 3 — Provider selection

`AI_VALIDATION_PROVIDER` (Constance) controls which API is used:

| Setting | Behaviour |
|---------|-----------|
| `"anthropic"` / `"openai"` / `"gemini"` / `"groq"` | Use that provider only |
| `"all"` (default) | Try providers in order: anthropic → openai → gemini → groq; move to next on failure |

### Step 4 — Retry loop

For each provider, up to 3 attempts are made:

- **Transient errors** (timeout, connection reset, rate limit, 5xx): retried with exponential back-off (1s, 2s).
- **Non-transient errors** (missing API key, auth failure, bad JSON): break immediately — no point retrying.

If a provider exhausts all retries, a fallback `AIValidationLog` is written and the pipeline continues to the next provider (in `"all"` mode) or returns flagged (single-provider mode).

---

## 5. AI Provider Adapters

**File:** `apps/provider/ai_validation.py`

Each adapter follows the same contract:

```python
def _call_<provider>(system, text, docs) -> (report_dict, raw_str, latency_ms, in_tokens, out_tokens, model_id)
```

| Provider | Model | PDF support |
|----------|-------|-------------|
| Anthropic | `claude-opus-4-8` | Yes — `document` content block |
| OpenAI | `gpt-4o-mini` | No — sends a text note instead of inline PDF |
| Gemini | `gemini-2.0-flash` | Yes — `inline_data` with `mime_type=application/pdf` |
| Groq | `meta-llama/llama-4-scout-17b-16e-instruct` | No — same as OpenAI |

Anthropic is the default first provider and uses **Opus** (`claude-opus-4-8`) — the
most accurate model at reading small/degraded ID text (Arabic-Indic digits, the
two-line NID name). Identity validation is low-volume and asynchronous, so the
accuracy is worth the higher per-call cost; tune `_ANTHROPIC_MODEL` in
`ai_validation.py` to trade accuracy for cost.

**PDF handling:** Anthropic and Gemini receive PDFs natively. OpenAI and Groq receive a text note: `"(application/pdf document was provided but cannot be visually inspected by this model)"` so they can still reason about what was submitted even without seeing it.

**API keys** are read from Django settings at call time (not at import time), so `override_settings` in tests works correctly and missing keys fail fast with a non-transient `ValueError`.

---

## 6. Prompt Design

**File:** `apps/provider/ai_validation.py`

### System prompt

Sets the model's role and Egypt-specific context:

- Documents are in Arabic; transliteration equivalence is explicitly required (`"أحمد محمد علي"` and `"Ahmed Mohamed Ali"` are the same person).
- Both modern NID card formats are described (14-digit `بطاقة الرقم القومي` and older `بطاقة تحقيق الشخصية`).
- The model's role is to surface factual problems, **not** to make final approval decisions.

### Document prompt

Templated at runtime with applicant data:

```
Full name : {full_name}
Date of birth : {dob}   (DD/MM/YYYY)
Phone : {phone}
Documents provided: [list of labels and whether each was provided]
```

**Checks performed per document:**

| Document | Key checks |
|----------|-----------|
| NID Front | Valid Egyptian NID format; 14-digit number decodes to DOB matching form; name matches applicant; photo clear; no tampering |
| NID Back | Back of same card; issue/expiry dates legible; card not expired; official stamp present; no tampering |
| Police Clearance | Issued by Ministry of Interior; applicant name matches; issue date ≤ 5 months ago; clean-record phrase present; official stamp; no tampering |
| Professional Certificate | Relevant trade; recognisable issuing authority; name matches; no tampering |

**Response format:** The model is instructed to return **only** a JSON object — no prose, no markdown fences. A `_clean_json()` helper strips any accidental code fences before parsing.

```json
{
  "document_checks": {
    "nid_front":        {"valid": true|false|null, "notes": "..."},
    "nid_back":         {"valid": true|false|null, "notes": "..."},
    "police_clearance": {"valid": true|false|null, "notes": "..."},
    "professional_cert":{"valid": true|false|null, "notes": "..."}
  },
  "extracted_data": {
    "nid_number":     "14-digit number or null",
    "name_on_nid":    "FULL name across both lines (own name first), Arabic, or null",
    "dob_on_nid":     "DD/MM/YYYY or null",
    "address_on_nid": "address text or null",
    "issue_date":     "DD/MM/YYYY or null",
    "expiry_date":    "DD/MM/YYYY or null"
  },
  "name_match":           {"consistent": true|false|null, "notes": "NID name vs form name"},
  "age_check":            {"consistent": true|false|null, "notes": "NID DOB vs form DOB"},
  "identity_consistency": {"same_person": true|false|null, "notes": "same individual across all docs?"},
  "issues":      ["..."],
  "overall_confidence": 0.0
}
```

`name_match`, `age_check`, and `identity_consistency` are scored as identity red
flags: a `false` on any of them forces at least `flagged` (never `passed`), so a
borrowed/forged ID or a name/DOB mismatch can't slip through as a clean pass.

**Egyptian name handling:** Egyptian full names are a chain (`own · father ·
grandfather · family`) printed across two lines on the NID. The prompt instructs
the model to read **both** lines and start at the applicant's own first name —
otherwise it drops the first name and mistakes the father's name for the
applicant's.

`null` means the model couldn't determine validity (blurry, not provided, etc.) — distinct from `false` (definitely invalid).

**`extracted_data`** is a faithful OCR transcription of the NID — real applicant
data the platform keeps, not just debug output. The full report (including
`extracted_data`) is stored on `ProviderOnboarding.ai_validation_report`, and the
OCR block is **also** copied to the dedicated `ProviderOnboarding.nid_extracted_data`
field so it stays queryable (e.g. search an applicant by NID number in the admin).
On **approval**, `ProviderOnboarding.approve()` copies that block onto
`Provider.nid_extracted_data`, so the verified identity record lives on the
provider account (shown read-only in the Provider admin, searchable by NID number).

**Deterministic DOB.** The Egyptian national ID number encodes the date of birth
in its **first 7 digits** (digit 1 = century, digits 2–7 = `YYMMDD`). Rather than
trust the model to read the printed date, `decode_nid_dob()` derives the DOB from
those leading digits in code — it tolerates a partially-read number (e.g. 11 of 14
digits) since the DOB sits at the start, and rejects implausible results. Then
`_apply_nid_dob_decode()` writes the decoded value into `dob_on_nid` and recomputes
the age check against the form DOB, removing a whole class of date-misreads. (The
model is also told `nid_number` is the national number — *not* the short card
serial like `IW…` — and to read it left-to-right from the first digit.)

---

## 7. Result Scoring

After a successful API call, the pipeline derives a final `status` from the raw report:

```python
any_invalid = any(check.get("valid") is False for check in document_checks.values())

if any_invalid and confidence < 0.4:
    status = "failed"
elif any_invalid or issues or confidence < 0.5:
    status = "flagged"
else:
    status = "passed"
```

| `status` | Meaning | Staff action |
|----------|---------|--------------|
| `passed` | Documents look legitimate | Can approve directly if no other concerns |
| `flagged` | Issues found or confidence low | Must review AI report before deciding |
| `failed` | Clearly invalid documents + very low confidence | Strong signal to reject, but staff still decides |

`status` is injected into the report dict (`report["status"] = status`) and stored on the `ProviderOnboarding.ai_validation_report` JSON field.

---

## 8. Fallback Paths

Every error is caught and degraded gracefully. The queue never stalls.

| Failure | Outcome | Application visible to staff? |
|---------|---------|-------------------------------|
| `AI_VALIDATION_ENABLED = False` | `bypassed` — instant pass | Yes, `ai_validation_status=PASSED` |
| No readable documents on disk | `flagged` — early return, no API call | Yes |
| Missing API key | `flagged` — non-transient, no retries | Yes |
| Transient error (timeout, rate limit) | Retry up to 3×, then `flagged` | Yes |
| Bad JSON from model | `flagged` — non-transient | Yes |
| All providers fail (`"all"` mode) | `flagged` — last provider's error result | Yes |
| Task max retries exhausted | `_mark_flagged()` → `FLAGGED` | Yes |

**Fallback report shape:**

```json
{
  "status": "flagged",
  "issues": ["AI validation service error — manual review required"],
  "document_checks": {
    "nid_front":        {"valid": null, "notes": "validation unavailable"},
    ...
  },
  "age_check": {"consistent": null, "notes": "validation unavailable"},
  "overall_confidence": 0.5
}
```

`overall_confidence: 0.5` signals to staff that this is an uncertain/fallback result, not a genuine assessment.

---

## 9. Audit Log

**Model:** `apps/provider/models.py` — `AIValidationLog`

Every call — including bypasses and errors — writes an immutable log row:

| Field | Purpose |
|-------|---------|
| `onboarding` | FK to `ProviderOnboarding` (nullable; survives row deletion) |
| `outcome` | `passed / flagged / failed / bypassed / error` |
| `applicant_snapshot` | `{full_name, dob, phone}` captured at call time |
| `documents_sent` | List of document labels included in the API call |
| `raw_response` | Raw text from the model before JSON parsing |
| `parsed_report` | The final status-enriched report |
| `error_message` | Exception text when `outcome=error` |
| `model_id` | Which model was used (e.g. `claude-opus-4-8`) |
| `latency_ms` | Wall-clock time of the API call |
| `input_tokens` / `output_tokens` | Token usage for cost tracking |

The log is write-once from the application code. In the admin:
- `has_add_permission = False`
- `has_change_permission = False`
- `has_delete_permission` — superusers only (for cleanup)

One onboarding application can accumulate multiple log rows: one per submission, plus one per provider attempted in `"all"` mode, plus retry failures.

---

## 10. Runtime Controls (Constance)

All tuneable settings are in Django Admin → **Constance → Change** — no redeploy required.

| Key | Type | Default | Effect |
|-----|------|---------|--------|
| `AI_VALIDATION_ENABLED` | bool | `True` | `False` bypasses all API calls and auto-passes every submission |
| `AI_VALIDATION_PROVIDER` | str | `"all"` | Which adapter(s) to use: `anthropic`, `openai`, `gemini`, `groq`, `all` |
| `ONBOARDING_REJECTION_COOLDOWN_DAYS` | int | `30` | Days before a rejected provider can resubmit |
| `ONBOARDING_MAX_FILE_SIZE_MB` | int | `5` | Max upload size per document (enforced at model `clean()`) |
| `AI_RECOMMENDATION_ENABLED` | bool | `True` | `False` skips AI calls on recommended bookings and returns plain-text reasons |
| `AI_RECOMMENDATION_PROVIDER` | str | `"all"` | Which adapter(s) to use for provider recommendations: `anthropic`, `openai`, `gemini`, `groq`, `all` |

**Operational tips:**
- Set `AI_VALIDATION_ENABLED = False` during load tests or when all AI APIs are degraded — applications still queue normally for staff review.
- Set `AI_VALIDATION_PROVIDER = "anthropic"` to pin to a single provider and avoid cascading latency when debugging.

**Real end-to-end smoke test:** `scripts/e2e_onboarding.py` builds a throwaway
onboarding from the local `test-data/` document images and runs the real
`validate_onboarding()` pipeline (real API call, real OCR). It prints a detailed
report — form-vs-card comparison, name/age/identity consistency, extracted NID
data, per-document checks, issues, and model/token/latency metadata — then deletes
the throwaway data. It is a **standalone dev script, not a management command**, so
it is never part of the shipped command surface or a deploy entrypoint. Run it in
the stack so the keys and Constance are available:

```bash
make e2e-onboarding                                  # cascade (all)
make e2e-onboarding provider=anthropic               # pin one provider
make e2e-onboarding provider=anthropic args="--keep" # keep the record for the admin
docker compose exec web python scripts/e2e_onboarding.py --name "Wrong Name" --dob 01/01/2010 --keep
```

It reads API keys from the environment and document images from `test-data/`
(gitignored — supply your own). Spends real API tokens.

---

## 11. Status Flow Diagram

### `ai_validation_status` lifecycle

```
              POST /onboarding/submit/
                        │
                        ▼
                   ┌─────────┐
                   │ PENDING │  ← set synchronously by the view
                   └────┬────┘
                        │  Celery task picks up (on_commit)
                        ▼
                   ┌─────────┐
                   │ RUNNING │  ← set at task start
                   └────┬────┘
            ┌───────────┼───────────┐
            ▼           ▼           ▼
        ┌────────┐ ┌─────────┐ ┌────────┐
        │ PASSED │ │ FLAGGED │ │ FAILED │
        └────────┘ └─────────┘ └────────┘
```

### `status` (onboarding FSM) alongside AI validation

```
                         PENDING  ←─── submit view sets this
                            │
                    AI running in background
                            │
                     ai_status = PASSED/FLAGGED/FAILED
                            │
                    Staff picks up in admin
                            │
                      UNDER_REVIEW
                     /      |      \
               APPROVED  REJECTED  CHANGES_REQUIRED
                                         │
                                  Provider re-uploads
                                         │
                                       DRAFT
                                         │
                                    Re-submit
                                         │
                                  (loop from PENDING)
```

---

## 12. Data Flow: End to End

```
┌─────────────────────────────────────────────────────────────────┐
│  Mobile App                                                     │
│  POST /api/v1/providers/onboarding/submit/                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  OnboardingSubmitView                                           │
│  1. Validate all required fields present                        │
│  2. Set status=PENDING, ai_validation_status=PENDING            │
│  3. DB save (within transaction)                                │
│  4. transaction.on_commit → enqueue Celery task                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │ Redis (Celery broker)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Celery Worker — validate_onboarding_documents(onboarding_id)   │
│  1. Load ProviderOnboarding from DB                             │
│  2. Set ai_validation_status=RUNNING, save                      │
│  3. Call validate_onboarding(onboarding)                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │ function call
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  validate_onboarding()   [ai_validation.py]                     │
│                                                                 │
│  Check AI_VALIDATION_ENABLED ──── False ──→ return BYPASS_RESULT│
│            │ True                                               │
│            ▼                                                    │
│  Encode documents (base64)                                      │
│  Build prompt (name, DOB, phone + doc list)                     │
│            │                                                    │
│  ┌─────────┴─────────────────────────────┐                      │
│  │  Provider loop (per AI_VALIDATION_     │                      │
│  │  PROVIDER setting)                    │                      │
│  │                                       │                      │
│  │  for attempt in range(3):             │                      │
│  │    try:                               │                      │
│  │      call adapter → raw JSON          │                      │
│  │      score result → passed/flagged/   │                      │
│  │                     failed            │                      │
│  │      write AIValidationLog            │                      │
│  │      return report ◄──────────────────┘                      │
│  │    except transient: sleep, retry     │                      │
│  │    except non-transient: break        │                      │
│  │                                       │                      │
│  │  write AIValidationLog (error)        │                      │
│  │  try next provider (if "all" mode)    │                      │
│  └───────────────────────────────────────┘                      │
│                                                                 │
│  All providers exhausted → return last fallback result          │
└───────────────────────────┬─────────────────────────────────────┘
                            │ dict
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Back in Celery task                                            │
│  Map status string → AIValidationStatus enum                    │
│  Save ai_validation_status + ai_validation_report to DB         │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Django Admin — ProviderOnboarding change view                  │
│  Staff sees:                                                    │
│   • AI status badge (PASSED / FLAGGED / FAILED)                 │
│   • Confidence percentage                                       │
│   • Issues list                                                 │
│   • Per-document check table (✔ / ✘ / -)                        │
│   • Age check result                                            │
│  Staff makes final decision: Approve / Reject / Changes Required│
└─────────────────────────────────────────────────────────────────┘
```

### External API calls per submission

```
validate_onboarding_documents (Celery)
    └── validate_onboarding (ai_validation.py)
            ├── _encode_file() × 2–4      [disk reads, no network]
            ├── _call_anthropic()          [api.anthropic.com]   ← if configured
            ├── _call_openai()             [api.openai.com]
            ├── _call_gemini()             [generativelanguage.googleapis.com]
            └── _call_groq()               [api.groq.com]
                                           (first success wins; others skipped)
```
