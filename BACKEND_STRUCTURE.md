# SnapFix — Backend Structure & Documentation

> Graduation Project Reference Document
> A Django REST Framework + GeoDjango backend for an on-demand home-services
> platform (think "Uber for plumbers/electricians"). It connects customers who
> need a service with verified providers, and manages the full job lifecycle —
> from booking, to provider matching, to payment settlement.

---

## 1. What the System Does

SnapFix is the backend (API + admin dashboard) for a mobile home-services app.
The platform handles four core problems:

1. **Onboarding & trust** — providers register, upload identity/legal documents,
   and are verified by AI + human staff before they can take jobs.
2. **Matching** — customers can broadcast a job to all eligible providers, book a
   favorite directly, or accept an **AI-scored recommendation**.
3. **Lifecycle** — every job moves through a strict state machine
   (`pending → assigned → quoted → confirmed → in_progress → completed`) with
   guards that prevent illegal transitions.
4. **Payments** — jobs settle through cash, card (Stripe), or in-app wallet, with
   provider earnings credited automatically on completion.

---

## 2. Technology Stack

| Layer | Technology |
| --- | --- |
| Language / Framework | Python, **Django 6.0**, **Django REST Framework** |
| Geospatial | **GeoDjango + PostGIS** (PostgreSQL) for location/distance queries |
| Authentication | **Knox** token authentication (per-device tokens) |
| Background jobs | **Celery** + **Redis** (broker) + **Celery Beat** (scheduler) |
| Push notifications | **Firebase Cloud Messaging** (`fcm-django`) |
| Payments | **Stripe** (manual-capture PaymentIntents) |
| AI providers | **OpenAI, Google Gemini, Groq, Anthropic Claude** (multi-provider cascade) |
| Runtime config | **django-constance** (live-editable settings, Redis-backed) |
| Deployment | **Docker / docker-compose**, Gunicorn, WhiteNoise, Railway |

---

## 3. High-Level Architecture

The project follows Django's "apps" pattern — each app is a self-contained domain
with its own models, serializers, views, and URLs.

```
snap-fix-api/
├── config/                 # Project config: settings, root URLs, Celery, WSGI/ASGI
├── apps/
│   ├── user/               # Shared base User model (identity for all roles)
│   ├── customer/           # Customer accounts, wallet, favorites
│   ├── provider/           # Provider accounts + onboarding FSM + AI doc validation
│   ├── core/               # Reference data: categories, regions, offices
│   ├── booking/            # ServiceRequest lifecycle, payments, reviews, AI matching
│   ├── staff/              # Admin/staff accounts with granular permissions
│   └── notifications/      # In-app inbox + FCM push dispatch
├── factories.py            # Unified model factories (tests + shell)
└── docker-compose.yml
```

**Inheritance model:** `Customer`, `Provider`, and `Staff` all inherit from a
single `User` model (multi-table inheritance). A `User` row is exactly one of
these three roles, resolved at runtime via `get_user_type()`.

---

## 4. The `user` App — Shared Identity

### `User` (model)
The concrete base model for everyone on the platform. Uses a UUID primary key and email
as the login field (no usernames), and carries shared profile fields — name, phone,
profile picture, and a PostGIS `location` point. `Customer`, `Provider`, and `Staff`
each extend it via one-to-one multi-table inheritance.

- `get_user_type()` — returns `"customer"`, `"provider"`, or `"staff"` by checking
  which reverse relation exists, so views can branch on the caller's role.
- `get_full_name()` — convenience join of first + last name, used across notifications.

---

## 5. The `core` App — Reference Data

### `Category` (model)
A service type a provider can operate in (e.g. Plumbing, Electrical). Has a name,
slug, emoji icon, and display order. Providers register against one or more
categories, and jobs are matched only to providers in the matching category.

### `Region` (model)
A geographic operating area (e.g. Cairo, Alexandria) with a center `location` point.
Exposes `latitude` / `longitude` convenience properties and a `set_location(lat, lng)`
helper that builds a PostGIS `Point` in the correct coordinate order.

### `Office` (model)
A physical office location with address, landmark, working hours, and a geo point.
Used by the "find nearest office" feature; managed exclusively through the admin.

### Views (`core/views.py`)
- `CategoryListView` / `RegionListView` / `OfficeListView` — public, read-only lists
  of active reference data the mobile app needs to populate dropdowns and maps.
- `NearestOfficeView` — takes `lat`/`lng` query params, validates the range, and
  returns the single closest active office using a PostGIS `Distance` annotation.

---

## 6. The `customer` App — Buyers

### `Customer` (model)
A user who books services. Adds a **wallet** (`wallet_balance`, `total_cashback`),
a many-to-many `favorite_providers` relation, and a `total_bookings` counter.
All wallet mutations go through safe helper methods rather than raw field writes.

- `add_to_wallet()` / `deduct_from_wallet()` — credit/debit with a balance guard;
  deduct returns `False` (no-op) when funds are insufficient.
- `add_cashback()` — credits the wallet and tracks lifetime cashback together.
- `increment_bookings()` — bumps the booking counter on job completion.

### Views (`customer/views.py`)
- `CustomerRegisterView` / `CustomerLoginView` — public endpoints that create the
  account and issue a Knox token in one response.
- `CustomerLogoutView` — Knox-backed token deletion.
- `CustomerProfileView` — `GET`/`PATCH /me/`; locks sensitive fields (wallet,
  verification) so they can't be edited through the profile endpoint.
- `CustomerFavoriteToggleView` — idempotent add/remove of a provider from favorites.
- `CustomerFavoritesListView` — lists the customer's saved providers.

---

## 7. The `provider` App — Sellers & Onboarding

This is the most complex app, covering provider accounts, a document-verification
finite state machine, and an AI document-validation pipeline.

### `Provider` (model)
A verified service professional. Extends `User` with business fields (`business_name`,
`bio`, `hourly_rate`, `service_radius`), money fields (`total_earnings`,
`available_balance`), and reputation stats (`average_rating`, `total_jobs`,
`completed_jobs`, `declined_jobs`). A `verification_status` field gates whether the
provider can log in and take jobs.

- `add_earnings()` / `withdraw_balance()` — adjust the provider's balances safely.
- `get_completion_rate()` — percentage of assigned jobs actually completed.
- `acceptance_rate` (property) — `(total_jobs − declined_jobs) / total_jobs`,
  `None` for brand-new providers with no history.
- `update_rating()` — recalculates the running average rating in a single atomic
  SQL `UPDATE` (avoids race conditions when two reviews land at once).

### `ProviderOnboarding` (model)
The single source of truth for a provider's verification application. Holds personal
details, uploaded documents (NID front/back, police clearance, certificates), the
review state, and the AI validation report. It is a **finite state machine**:

```
draft → pending → under_review → approved
                              ↘ rejected   (30-day cooldown → resubmit → draft)
                              ↘ changes_required → pending (repeat)
```

- `clean()` — enforces age 18+, email/applicant consistency, and per-file size limits.
- `move_to_review()` / `approve()` / `reject()` / `request_changes()` / `resubmit()` —
  guarded FSM transitions; each checks the current state before advancing.
- `approve()` (atomic) — activates the linked `Provider` account, copies the
  reviewed details onto it, and flips `verification_status` to `verified`.
- `can_resubmit` (property) — `True` only once the rejection cooldown has elapsed.

### `AIValidationLog` (model)
An immutable audit record of every AI document-validation call — inputs sent,
raw/parsed responses, latency, token usage, and outcome. Kept for monitoring and
debugging; survives even if the onboarding row is deleted.

### AI Document Validation (`provider/ai_validation.py`)
Inspects identity documents with a vision-capable LLM **before** a human reviewer
sees them. Designed to never block the queue — every failure path returns a
"flagged" result for manual review.

- `validate_onboarding(onboarding)` — the entry point. Encodes each document to
  base64, builds an Egypt-specific prompt (Arabic NID/police-clearance checks,
  transliteration-aware name matching), and runs the configured provider cascade.
  Classifies the result as `passed` / `flagged` / `failed` from the model's findings.
- `_call_openai` / `_call_gemini` / `_call_groq` / `_call_anthropic` — per-provider
  adapters; Anthropic and Gemini handle PDFs natively, the others get a text note.
- `_is_transient()` — decides whether an error is worth retrying (timeout, rate
  limit, 5xx) versus a hard failure (missing key, auth) that breaks the loop.
- `_encode_file()` / `_clean_json()` / `_fallback()` — helpers for reading files,
  stripping markdown fences from model output, and producing the safe fallback report.

### Views (`provider/views.py`)
- `ProviderRegisterView` — creates the account and issues a scoped **onboarding token**
  (full login is blocked until approval).
- `ProviderLoginView` — succeeds only when the account is active *and* verified.
- `ProviderProfileView` / `ProviderLocationView` — profile read/update and a
  lightweight GPS-ping endpoint the app calls while a provider is on a job.
- `OnboardingPersonalInfoView` / `OnboardingDocumentsView` / `OnboardingSubmitView` /
  `OnboardingStatusView` — the self-service onboarding flow: fill details, upload
  docs, submit for review (which enqueues AI validation), and poll status.

### Background Tasks (`provider/tasks.py`)
- `validate_onboarding_documents` — Celery task triggered on submit; runs the AI
  validation, stores the report, and retries with back-off, falling back to
  "flagged" so an application never silently stalls.
- `notify_resubmit_available` — daily beat task that pushes a reminder when a
  rejected provider's cooldown expires.

### Admin (`provider/admin.py`)
A rich custom admin is where staff actually review applications. It renders document
previews, an **AI validation report panel** (confidence, per-document checks, issues),
and enforces the same FSM rules on save — approving an application activates the
provider account and fires an approval push notification.

---

## 8. The `booking` App — The Heart of the Platform

### `ServiceRequest` (model)
The central transaction object — one row per job. Holds the parties (customer,
provider), the request details (category, region, geo-pinned address, title,
description, urgency, scheduling), pricing (`estimated_price` → `quoted_price` →
`final_price`), payment fields, status, and a full set of lifecycle timestamps.
It encapsulates the **entire state machine** as guarded, mostly-atomic methods:

- `assign()` / `self_assign()` — admin assigns a provider, or a provider picks a job
  from the open pool; `self_assign()` uses a row lock + active-job guard to stay
  race-free under concurrent picks.
- `quote()` / `approve_quote()` / `reject_quote()` — the price-negotiation path;
  `approve_quote()` locks `final_price` and re-validates the customer's wallet balance.
- `confirm()` — the skip-quote path where a provider accepts directly.
- `start()` / `complete()` — provider begins and finishes work; `complete()` is where
  **payment settles** (see §11) and provider/customer stats are credited.
- `cancel()` / `decline()` — terminate or return a job to the pool, adjusting the
  provider's `total_jobs` / `declined_jobs` counters and audit fields accordingly.
- `card_amount` (property) — derived `final_price − wallet_amount`.
- `_capture_stripe_payment()` — captures the manual-capture Stripe PaymentIntent at
  completion, raising on failure so the whole transaction rolls back atomically.

### `ServiceRequestPhoto` (model)
Photos attached to a request (1–5 required at creation). Stored as image files and
returned in every request payload so both parties see the same evidence of the job.

### `Review` (model)
A customer's 1–5 star rating + comment for a completed job, one-to-one with the
request. A DB check constraint enforces the rating range, and creating one triggers
the provider's `update_rating()`.

### `AIRecommendationLog` (model)
Audit log mirroring `AIValidationLog`, but for the recommendation flow — records the
scored candidate snapshot, the AI's parsed reasons, latency, and outcome.

### Provider Matching — Scoring Engine (`booking/recommendation.py`)
A shared, deterministic scoring engine used both by the recommendation flow and the
provider "open requests" view, so customers and providers see consistent match quality.

- `score_provider(provider, distance_km, is_urgent, is_favorite)` — produces a
  weighted 0–100 score plus a per-signal breakdown. Weights: **rating 30%, distance
  25%, completion rate 20%, favorite bonus 15%, urgency availability 10%**.
- `get_top_providers(category, location, is_urgent, customer)` — queries eligible
  providers (verified, available, right category), pre-filters by a PostGIS
  bounding box for efficiency, scores each, drops those outside their own service
  radius, and returns the top 3.

### AI Recommendation Reasons (`booking/ai_recommendation.py`)
Turns the numeric scores into one friendly sentence per provider ("Highly rated and
only 1.2 km away…"). Architecturally identical to the validation pipeline.

- `generate_recommendation_reasons(scored_providers, …)` — entry point; builds a
  prompt from the signals, runs the provider cascade, and **never raises** — it falls
  back to rule-based `_generic_reasons()` derived directly from the scores when AI is
  disabled or every provider fails.

### Views (`booking/views.py`)
**Customer-facing:**
- `ServiceRequestListView` — list own requests / create a new one (enforces the 1–5
  photo rule; for `recommended` mode it embeds the scored top-3 in the response).
- `DirectBookingView` / `RecommendedBookingView` — create a job and atomically assign
  it to a chosen favorite (direct) or AI-recommended (recommended) provider, with
  full availability/category/busy guards under a row lock.
- `CustomerApproveQuoteView` / `CustomerRejectQuoteView` — accept or reject the
  provider's price; approve also confirms the payment split.
- `InitiateCardPaymentView` — attaches a Stripe PaymentMethod and creates a
  manual-capture PaymentIntent (authorize now, charge at completion).
- `CustomerCancelView` / `CustomerRateProviderView` — cancel a job or leave a review.

**Provider-facing:**
- `ProviderOpenRequestsView` — the open job pool for the provider's categories,
  sorted urgent-first then nearest-first, each annotated with the provider's own
  `match_score`.
- `ProviderIncomingRequestsView` / `ProviderPickRequestView` — jobs awaiting action,
  and self-assigning one from the pool.
- `ProviderQuoteView` / `ProviderAcceptView` / `ProviderDeclineView` — submit a price,
  accept directly, or decline back to the pool.
- `ProviderStartView` / `ProviderCompleteView` / `ProviderCancelView` — start, finish
  (settles payment), or cancel a job.

**Shared:**
- `HistoryDetailView` — one endpoint, two serializers: returns the customer-oriented
  or provider-oriented detail view depending on the caller's role.

**Helpers:** `fsm_transition()` wraps every state change to convert a model-level
`ValueError` into a clean `400` response; `get_customer_or_403` / `get_provider_or_403`
enforce role at the view boundary.

---

## 9. The `staff` App — Admin Operators

### `Staff` (model)
An internal operator who works in the admin dashboard. Adds four granular permission
flags — `can_manage_users`, `can_manage_services`, `can_manage_payments`,
`can_view_analytics` — all defaulting to `False` (least privilege).

- `has_permission(type)` — checks a specific permission via the `PERM_*` constants.
- `save()` — always forces `is_staff = True` so staff get admin access.

---

## 10. The `notifications` App — Inbox & Push

### `Notification` (model)
A persisted in-app inbox entry that maps 1-to-1 with an FCM push. Carries a `type`
(used by the mobile app to decide which screen to open), `title`/`body`, and a `data`
payload (usually the related `service_request_id`).

### Notification Service (`notifications/service.py`)
The single entry point for all notifications. Persisting the inbox row is synchronous
(always reliable), while the push is enqueued asynchronously after the DB transaction
commits — so a push is never sent for a job state that rolled back.

- `notify(recipient, type, title, body, data)` — the core dispatcher: saves the row,
  then fires the Celery push task on commit (failing softly if the broker is down).
- Per-event helpers (`notify_customer_quote_received`, `notify_provider_quote_approved`,
  `notify_provider_onboarding_approved`, …) — one readable function per lifecycle
  event, each calling `notify()` with the right copy and recipient.

### Background Tasks (`notifications/tasks.py`)
- `send_push_notification` — sends the FCM message to all of a user's active devices;
  configured for at-least-once delivery with a 60s→120s→240s retry schedule.
- `purge_stale_fcm_devices` / `purge_old_notifications` — scheduled cleanup tasks for
  silent device tokens (90+ days) and old read notifications.

### Views (`notifications/views.py`)
- `NotificationListView` / `UnreadCountView` — the inbox and its unread badge count.
- `MarkReadView` / `MarkAllReadView` — mark one or all notifications read.
- `RegisterDeviceView` / `UnregisterDeviceView` — register/deactivate an FCM device
  token (rate-limited, capped at 5 active devices per user).

---

## 11. Cross-Cutting Flows

### Booking State Machine
```
pending → assigned → quoted → confirmed → in_progress → completed   (terminal)
                  ↘ (provider accepts directly) ↗
quoted   → pending   (customer rejects quote)
assigned → pending   (provider declines)
cancelled            (from any non-terminal state, terminal)
```
Guards enforced on every transition: ≥1 photo to create, one active job per provider,
category must match, DB row lock on pool picks, and a locked `final_price` that can't
change after quote approval.

### Three Booking Modes
| Mode | How it works |
| --- | --- |
| `broadcast` | Job enters the open pool; any matching provider self-assigns. |
| `direct` | Customer books a specific favorite; assigned atomically at creation. |
| `recommended` | API scores eligible providers, returns top 3 with AI reasons; customer picks one. |

### Payment Settlement (at `complete()`)
- **Cash** — provider collects in person; marked paid on the honor system (platform
  doesn't credit the cash portion to `available_balance`).
- **Card** — the pre-authorized Stripe PaymentIntent is captured; provider credited.
- **Wallet** — the wallet amount is deducted under a row lock; provider credited.
All three update the provider's `completed_jobs` / `total_earnings` and the customer's
`total_bookings` once everything succeeds, inside one atomic transaction.

### Multi-Provider AI Cascade
Both AI features (document validation and recommendation reasons) share the same
resilience design: a runtime Constance flag to enable/disable, a configurable provider
order (OpenAI → Gemini → Groq → Anthropic, or a single one), 3 retries on transient
errors, automatic fall-through to the next provider, a deterministic non-AI fallback,
and a full audit log of every call.

---

## 12. Algorithms & Techniques

The backend applies a number of established algorithms and computer-science methods,
listed below by their formal (scientific) names, with the common term in parentheses.

| Formal / scientific name | Where it's used | What it achieves |
| --- | --- | --- |
| **Simple Additive Weighting (SAW)** — a Weighted Sum Model (WSM) from Multi-Criteria Decision Analysis (MCDA), with min–max feature scaling | Provider recommendation & open-pool ranking | Normalizes five criteria (rating, distance, completion rate, favorite, urgency) to a common 0–100 scale and combines them by fixed weights into one ranking score |
| **Haversine formula** — great-circle distance via spherical trigonometry | Provider↔job and user↔office distances | Computes the shortest surface distance between two latitude/longitude points on the Earth |
| **Spatial range query + k-Nearest-Neighbor (k-NN) search** over an R-tree / GiST index, with Minimum Bounding Rectangle (MBR) pre-filtering | Nearest office, candidate pre-filtering, open-job sorting | Finds and orders the closest entities in sub-linear time using a spatial index |
| **Deterministic Finite Automaton (DFA)** — finite-state machine with guarded (partial) transition functions | Service-request lifecycle & provider onboarding | Accepts only the defined sequence of states and rejects every illegal transition |
| **Cumulative Moving Average (CMA)** — online / incremental mean update | Provider rating aggregation | Updates the average from the prior average plus the new rating in O(1), without rescanning history |
| **Pessimistic Concurrency Control (PCC)** via Two-Phase Locking (2PL) — exclusive row locks under ACID isolation | Job picking, direct booking, wallet settlement | Serializes competing transactions so shared state stays consistent under concurrency |
| **Truncated exponential backoff** with cascading failover (graceful degradation) | AI pipelines & push-notification delivery | Spaces out retries on transient faults (1s→2s→4s) and falls through to alternatives, with a deterministic fallback |
| **Multimodal Vision-Language Model (VLM) inference** — optical character recognition (OCR) + document classification | Onboarding document verification | Extracts and cross-checks fields from identity/legal document images |
| **Natural Language Generation (NLG)** via an autoregressive transformer (LLM) | Recommendation reasons | Produces human-readable justification text from the structured match signals |
| **Bearer-token authentication** with cryptographically hashed token digests | All authenticated endpoints (Knox) | Stateless, per-device, revocable session authentication |

---

## 13. Configuration & Operations (`config/`)

- **`settings.py`** — installed apps, PostGIS database, Knox auth defaults, CORS,
  Stripe/AI API keys (all read from environment variables — no secrets in code),
  Constance runtime settings, and the Celery Beat schedule.
- **`urls.py`** — versioned API routing under `/api/v1/` plus the custom admin and a
  branded landing page.
- **`celery.py`** — the Celery app that auto-discovers each app's `tasks.py`.
- **Scheduled jobs** — purge stale FCM devices (daily), purge old notifications
  (weekly), and notify providers when their resubmit cooldown lifts (daily).

### Runtime-Togglable Settings (Constance)
`AI_VALIDATION_ENABLED`, `AI_VALIDATION_PROVIDER`, `AI_RECOMMENDATION_ENABLED`,
`AI_RECOMMENDATION_PROVIDER`, `ONBOARDING_REJECTION_COOLDOWN_DAYS`,
`ONBOARDING_MAX_FILE_SIZE_MB` — all editable live from the admin without a redeploy.

---

## 14. Testing

Each app ships a `tests/` package (`test_views`, `test_recommendations`,
`test_provider_onboarding`, `test_notifications`, …). A root-level `factories.py`
provides unified model factories with safe defaults, used by both the test suite and
interactive shell sessions, plus a `scaffold()` helper that builds a fully-linked
object graph in one call.

---

## 15. API Surface (Summary)

All endpoints are under `/api/v1/` and require a Knox token except registration/login.

| Group | Key endpoints |
| --- | --- |
| Customers | `register`, `login`, `me`, `favorites`, `favorites/<id>/toggle` |
| Providers | `register`, `login`, `me`, `me/location`, `onboarding/{personal,documents,submit,status}` |
| Core | `categories`, `regions`, `offices`, `offices/nearest` |
| Bookings | `requests` (+ `direct`, `recommended`, `open`, `incoming`), and per-job actions: `pick`, `quote`, `accept`, `decline`, `start`, `complete`, `cancel`, `approve-quote`, `reject-quote`, `initiate-card-payment`, `rate`, `history/<id>` |
| Notifications | inbox list, `unread-count`, `read`/`read-all`, `devices/register` |

> Full request/response shapes are documented in `URLs.md`.

---

*This document summarizes the backend as implemented. For deeper detail see the
companion docs: `URLs.md` (API reference), `AI_VALIDATION_PIPELINE.md`,
`AI_RECOMMENDATION.md`, `PAYMENT_FLOW.md`, `PROVIDER_ONBOARDING.md`, and
`NOTIFICATIONS.md`.*
