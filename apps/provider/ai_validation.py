"""
AI document validation for provider onboarding.

Uses multiple AI providers to inspect identity documents before a human
reviewer sees the application. Non-blocking by design: every error path
(missing API key, unreadable file, API outage, bad JSON) falls back to a
"flagged" result so the onboarding queue never stalls waiting for AI.

Feature flag: AI_VALIDATION_ENABLED is a runtime-togglable setting managed
via Django Admin → Constance. Disable it to skip the API call and
auto-pass all documents instantly — useful for testing without restarting.

Provider: AI_VALIDATION_PROVIDER in Constance controls which API to use.
Options: anthropic, openai, groq, gemini, all.
If 'all' is selected, the pipeline falls back to the next provider upon
failure. Each provider call is retried up to 3 times for transient errors
(network, timeout, rate-limit, 5xx). Non-transient errors (missing API key,
auth failure) break out of the retry loop immediately.
"""

from __future__ import annotations

import base64
import copy
import json
import logging
import mimetypes
import time

from constance import config
from django.conf import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a document-verification assistant for a home-services platform operating in Egypt.
You review Egyptian identity and legal documents, which are written in Arabic. The
registration form accepts both Arabic and English names (transliterated), so Arabic names
on documents and English names on the form are the SAME person — do not flag
transliteration differences as a name mismatch. Apply semantic equivalence:
"أحمد محمد علي" and "Ahmed Mohamed Ali" are a match; "أحمد محمد علي" and
"Mohamed Tarek Hassan" are not.

Egyptian NID cards come in two formats:
- Modern بطاقة الرقم القومي: shows a 14-digit national ID number on the front.
- Older بطاقة تحقيق الشخصية: an older blue/green card; also valid.

Your role is to surface factual problems for a human reviewer, not to make final decisions.
Be concise, factual, and note any uncertainty rather than guessing.
"""

_DOCUMENT_PROMPT = """\
Review the following onboarding documents for a service-provider applicant in Egypt.

Applicant details (from the registration form — names may be Arabic or English transliteration):
- Full name : {full_name}
- Date of birth : {dob}  (applicant must be 18 or older; date is formatted as DD/MM/YYYY)
- Phone : {phone}

Documents provided:
{doc_list}

━━━ CHECKS TO PERFORM ━━━

NID FRONT (بطاقة الرقم القومي / بطاقة تحقيق الشخصية — front):
  a) Is this the front of an Egyptian National ID card (either modern or older format)?
  b) Is the 14-digit national ID number legible? If so, read it and verify the
     encoded date of birth: digit 1 is the century code (2=1900s, 3=2000s),
     digits 2–7 are YYMMDD. Report the extracted DOB in DD/MM/YYYY and confirm
     it matches the "{dob}" field above.
  c) Does the name on the NID (Arabic or transliterated) match "{full_name}"?
     (transliteration equivalence applies — see instructions above)
  d) Is the photo clear and unobstructed?
  e) Are there signs of tampering, digital editing, or physical alteration?

NID BACK (بطاقة الرقم القومي / بطاقة تحقيق الشخصية — back):
  a) Is this the back of the same Egyptian National ID card?
  b) Are the issue date and expiry date legible? If so, report them in DD/MM/YYYY.
     Flag as invalid if the card is expired.
  c) Is the issuing authority stamp/seal present and intact?
  d) Are there signs of tampering?

POLICE CLEARANCE (صحيفة الحالة الجنائية):
  a) Is this an official Egyptian police clearance certificate issued by the
     Ministry of Interior (وزارة الداخلية) or its delegated authority?
  b) Is the applicant's name on the certificate consistent with "{full_name}"
     (transliteration equivalence applies)?
  c) Is the issue date visible? The certificate footer typically states it is
     valid for 5 months. Flag if it is older than 5 months from today — clearances
     older than 5 months are not acceptable for home-services onboarding.
  d) Does the certificate contain the phrase "لا توجد أحكام جنائية مسجلة" (no criminal
     record) or equivalent clean-record language?
  e) Is the official stamp/seal present and legible?
  f) Are there signs of tampering?

PROFESSIONAL CERTIFICATE (if provided):
  a) Is this a legitimate professional or vocational certificate relevant to a
     home-services trade (e.g. plumbing, electrical, HVAC, carpentry)?
  b) Is the issuing authority recognisable (Egyptian trade union, TEVTA,
     vocational training centre, or accredited institution)?
  c) Is the certificate holder's name consistent with "{full_name}"?
  d) Are there signs of tampering?

━━━ RESPONSE FORMAT ━━━

Respond ONLY with a JSON object matching this exact schema (no extra text):
{{
  "document_checks": {{
    "nid_front":        {{"valid": true|false|null, "notes": "..."}},
    "nid_back":         {{"valid": true|false|null, "notes": "..."}},
    "police_clearance": {{"valid": true|false|null, "notes": "..."}},
    "professional_cert":{{"valid": true|false|null, "notes": "..."}}
  }},
  "age_check":   {{"consistent": true|false|null, "notes": "..."}},
  "issues":      ["concise description of each problem found — empty if none"],
  "overall_confidence": 0.0
}}

Rules:
- overall_confidence: 0.0 (very suspicious / unreadable) → 1.0 (everything checks out).
- If a document was not provided, set valid to null and notes to "not provided".
- If you cannot read a field clearly, say so in notes rather than guessing.
- Arabic-Indic numerals (٠١٢٣٤٥٦٧٨٩) are equivalent to Western numerals — read them normally.
- All dates should be interpreted and reported in DD/MM/YYYY format.
- Keep each notes value to one sentence.
- Do NOT make a final approve/reject decision — that is the human reviewer's job.
"""

_BYPASS_RESULT = {
    "status": "passed",
    "issues": [],
    "document_checks": {
        "nid_front": {"valid": True, "notes": "AI validation disabled"},
        "nid_back": {"valid": True, "notes": "AI validation disabled"},
        "police_clearance": {"valid": True, "notes": "AI validation disabled"},
        "professional_cert": {"valid": True, "notes": "AI validation disabled"},
    },
    "age_check": {"consistent": True, "notes": "AI validation disabled"},
    "overall_confidence": 1.0,
}

_SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _encode_file(file_field) -> dict | None:
    """Read a document file and return a base64-encoded payload dict.

    Returns {"mime": <mime_type>, "data": <base64_string>} for images and PDFs.
    Returns None if the file is missing, unreadable, or has an unsupported type.
    """
    if not file_field:
        return None
    try:
        path = file_field.path
        mime, _ = mimetypes.guess_type(path)
        if not mime:
            mime = "image/jpeg"
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode()
    except (FileNotFoundError, OSError, ValueError):
        logger.warning(
            "ai_validation: could not read file %s", getattr(file_field, "name", "?")
        )
        return None

    if mime == "application/pdf" or mime in _SUPPORTED_IMAGE_TYPES:
        return {"mime": mime, "data": data}
    # Unknown type — treat as JPEG so vision models can still attempt to read it.
    return {"mime": "image/jpeg", "data": data}


def _is_transient(exc: Exception) -> bool:
    """True for errors worth retrying: network failures, timeouts, rate limits, 5xx."""
    cls = type(exc).__name__
    if any(
        cls.endswith(suffix)
        for suffix in (
            "TimeoutError",
            "ConnectionError",
            "RateLimitError",
            "InternalServerError",
            "ServiceUnavailableError",
            "RetryError",
            "APIConnectionError",
        )
    ):
        return True
    msg = str(exc).lower()
    return any(
        kw in msg
        for kw in (
            "timeout",
            "timed out",
            "rate limit",
            "connection reset",
            "service unavailable",
            " 503",
            " 502",
            " 529",
        )
    )


def _fallback(reason: str) -> dict:
    return {
        "status": "flagged",
        "issues": [reason],
        "document_checks": {
            "nid_front": {"valid": None, "notes": "validation unavailable"},
            "nid_back": {"valid": None, "notes": "validation unavailable"},
            "police_clearance": {"valid": None, "notes": "validation unavailable"},
            "professional_cert": {"valid": None, "notes": "validation unavailable"},
        },
        "age_check": {"consistent": None, "notes": "validation unavailable"},
        "overall_confidence": 0.5,
    }


def _write_log(
    onboarding,
    *,
    outcome: str,
    applicant_snapshot: dict,
    documents_sent: list,
    parsed_report: dict,
    raw_response: str = "",
    error_message: str = "",
    model_id: str = "",
    latency_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    try:
        from .models import AIValidationLog

        AIValidationLog.objects.create(
            onboarding=onboarding,
            outcome=outcome,
            applicant_snapshot=applicant_snapshot,
            documents_sent=documents_sent,
            parsed_report=parsed_report,
            raw_response=raw_response,
            error_message=error_message,
            model_id=model_id,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    except Exception:
        logger.exception("ai_validation: failed to write AIValidationLog")


def _clean_json(raw: str) -> dict:
    """Strip markdown code fences from model output and parse JSON."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned.strip())


# ── Provider adapters ─────────────────────────────────────────────────────────
# Each adapter returns: (report_dict, raw_str, latency_ms, in_tokens, out_tokens, model_id)
# PDFs: Anthropic and Gemini support them natively; OpenAI and Groq receive a
# text note instead (they only handle image_url content).


def _call_openai(system, text, docs):
    from openai import OpenAI

    api_key = getattr(settings, "OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = OpenAI(api_key=api_key)

    pdf_notes = [
        f"({d['mime']} document was provided but cannot be visually inspected by this model)"
        for d in docs
        if d["mime"] == "application/pdf"
    ]
    prompt = text + ("\n\nNote: " + "; ".join(pdf_notes) if pdf_notes else "")

    content = [{"type": "text", "text": prompt}]
    for d in docs:
        if d["mime"] != "application/pdf":
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{d['mime']};base64,{d['data']}"},
                }
            )

    model_id = "gpt-4o-mini"
    t_start = time.monotonic()
    response = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_object"},
        max_tokens=1024,
    )
    latency_ms = int((time.monotonic() - t_start) * 1000)
    raw = response.choices[0].message.content
    return (
        _clean_json(raw),
        raw,
        latency_ms,
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
        model_id,
    )


def _call_groq(system, text, docs):
    from groq import Groq

    api_key = getattr(settings, "GROQ_API_KEY", "")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set")
    client = Groq(api_key=api_key)

    pdf_notes = [
        f"({d['mime']} document was provided but cannot be visually inspected by this model)"
        for d in docs
        if d["mime"] == "application/pdf"
    ]
    prompt = text + ("\n\nNote: " + "; ".join(pdf_notes) if pdf_notes else "")

    content = [{"type": "text", "text": prompt}]
    for d in docs:
        if d["mime"] != "application/pdf":
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{d['mime']};base64,{d['data']}"},
                }
            )

    model_id = "meta-llama/llama-4-scout-17b-16e-instruct"
    t_start = time.monotonic()
    response = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_object"},
        max_tokens=1024,
    )
    latency_ms = int((time.monotonic() - t_start) * 1000)
    raw = response.choices[0].message.content
    return (
        _clean_json(raw),
        raw,
        latency_ms,
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
        model_id,
    )


def _call_gemini(system, text, docs):
    import google.generativeai as genai

    api_key = getattr(settings, "GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    model_id = "gemini-2.0-flash"
    model = genai.GenerativeModel(model_id, system_instruction=system)

    # Gemini supports both image and PDF inline_data with the same API shape.
    contents = [text]
    for d in docs:
        contents.append({"mime_type": d["mime"], "data": base64.b64decode(d["data"])})

    t_start = time.monotonic()
    response = model.generate_content(
        contents, generation_config={"response_mime_type": "application/json"}
    )
    latency_ms = int((time.monotonic() - t_start) * 1000)
    raw = response.text

    usage = getattr(response, "usage_metadata", None)
    in_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
    out_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

    return _clean_json(raw), raw, latency_ms, in_tokens, out_tokens, model_id


def _call_anthropic(system, text, docs):
    import anthropic

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)

    content = []
    for d in docs:
        if d["mime"] == "application/pdf":
            content.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": d["data"],
                    },
                }
            )
        else:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": d["mime"],
                        "data": d["data"],
                    },
                }
            )
    content.append({"type": "text", "text": text})

    model_id = "claude-haiku-4-5-20251001"
    t_start = time.monotonic()
    message = client.messages.create(
        model=model_id,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    latency_ms = int((time.monotonic() - t_start) * 1000)
    raw = message.content[0].text.strip()
    return (
        _clean_json(raw),
        raw,
        latency_ms,
        message.usage.input_tokens,
        message.usage.output_tokens,
        model_id,
    )


_PROVIDERS = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "gemini": _call_gemini,
    "groq": _call_groq,
}


def validate_onboarding(onboarding) -> dict:
    """Run AI document validation for a provider onboarding application.

    Returns a status dict:
      {"status": "passed"|"flagged"|"failed", "issues": [...], "document_checks": {...},
       "age_check": {...}, "overall_confidence": 0.0–1.0}

    Never raises — every failure path returns a "flagged" fallback so the
    onboarding queue keeps moving.
    """
    dob_str = (
        onboarding.date_of_birth.strftime("%d/%m/%Y")
        if onboarding.date_of_birth
        else ""
    )
    applicant_snapshot = {
        "full_name": onboarding.get_full_name(),
        "dob": dob_str,
        "phone": onboarding.phone,
    }

    if not getattr(config, "AI_VALIDATION_ENABLED", True):
        logger.info("ai_validation: disabled via Constance flag — returning passed")
        _write_log(
            onboarding,
            outcome="bypassed",
            applicant_snapshot=applicant_snapshot,
            documents_sent=[],
            parsed_report=_BYPASS_RESULT,
        )
        return copy.deepcopy(_BYPASS_RESULT)

    doc_labels = {
        "nid_front": onboarding.nid_front,
        "nid_back": onboarding.nid_back,
        "police_clearance": onboarding.police_clearance_certificate,
        "professional_cert": onboarding.professional_certificate,
    }

    docs_payload = []
    documents_sent = []
    doc_list_lines = []

    for label, field in doc_labels.items():
        block = _encode_file(field)
        if block:
            docs_payload.append(block)
            documents_sent.append(label)
            doc_list_lines.append(f"- {label}: provided")
        else:
            doc_list_lines.append(f"- {label}: NOT provided")

    if not docs_payload:
        result = _fallback("No documents were readable — manual review required")
        _write_log(
            onboarding,
            outcome="error",
            applicant_snapshot=applicant_snapshot,
            documents_sent=[],
            parsed_report=result,
            error_message="No readable documents found",
        )
        return result

    prompt_text = _DOCUMENT_PROMPT.format(
        full_name=applicant_snapshot["full_name"],
        dob=applicant_snapshot["dob"],
        phone=applicant_snapshot["phone"],
        doc_list="\n".join(doc_list_lines),
    )

    provider_setting = getattr(config, "AI_VALIDATION_PROVIDER", "all")
    if isinstance(provider_setting, str):
        provider_setting = provider_setting.lower()
    else:
        provider_setting = "all"

    if provider_setting == "all":
        provider_list = ["anthropic", "openai", "gemini", "groq"]
    elif provider_setting in _PROVIDERS:
        provider_list = [provider_setting]
    else:
        logger.warning(
            "ai_validation: unknown provider '%s', falling back to 'all'",
            provider_setting,
        )
        provider_list = ["anthropic", "openai", "gemini", "groq"]

    last_error_result = None
    last_error_message = "unknown error"

    for provider_name in provider_list:
        provider_func = _PROVIDERS[provider_name]
        succeeded = False

        for attempt in range(3):
            try:
                report, raw, latency, in_tokens, out_tokens, model_id = provider_func(
                    _SYSTEM_PROMPT, prompt_text, docs_payload
                )

                if not isinstance(report, dict):
                    raise ValueError(
                        f"{provider_name} returned JSON {type(report).__name__}, expected object"
                    )

                issues = report.get("issues", [])
                try:
                    confidence = max(
                        0.0, min(1.0, float(report.get("overall_confidence", 0.5)))
                    )
                except (TypeError, ValueError):
                    confidence = 0.5

                any_invalid = any(
                    v.get("valid") is False
                    for v in report.get("document_checks", {}).values()
                    if isinstance(v, dict)
                )

                if any_invalid and confidence < 0.4:
                    status = "failed"
                elif any_invalid or issues or confidence < 0.5:
                    status = "flagged"
                else:
                    status = "passed"

                report["status"] = status

                _write_log(
                    onboarding,
                    outcome=status,
                    applicant_snapshot=applicant_snapshot,
                    documents_sent=documents_sent,
                    parsed_report=report,
                    raw_response=raw,
                    model_id=model_id,
                    latency_ms=latency,
                    input_tokens=in_tokens,
                    output_tokens=out_tokens,
                )
                succeeded = True
                return report

            except Exception as exc:
                last_error_message = str(exc)
                if _is_transient(exc):
                    logger.warning(
                        "ai_validation: %s attempt %d/3 transient error: %s",
                        provider_name,
                        attempt + 1,
                        exc,
                    )
                    if attempt < 2:
                        time.sleep(2**attempt)  # 1s, 2s
                else:
                    logger.error(
                        "ai_validation: %s failed (non-transient): %s",
                        provider_name,
                        exc,
                    )
                    break  # No point retrying auth/config errors

        if not succeeded:
            last_error_result = _fallback(
                f"AI validation service error ({provider_name}) — manual review required"
            )
            _write_log(
                onboarding,
                outcome="error",
                applicant_snapshot=applicant_snapshot,
                documents_sent=documents_sent,
                parsed_report=last_error_result,
                error_message=f"{provider_name} failed: {last_error_message}",
            )

    return last_error_result
