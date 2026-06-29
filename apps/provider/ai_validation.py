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
import re
import time
from datetime import date

from constance import config
from django.conf import settings

logger = logging.getLogger(__name__)

# Arabic-Indic (٠-٩) and extended/Persian (۰-۹) digits → ASCII, so a number the
# model returns in Arabic numerals still decodes.
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def decode_nid_dob(nid_number: str | None) -> date | None:
    """Decode the date of birth from an Egyptian national ID number.

    The DOB is encoded in the FIRST 7 digits — digit 1 is the century (2 → 1900s,
    3 → 2000s) and digits 2–7 are YYMMDD. Those digits sit at the very start of the
    number (its most legible part), so the DOB is recoverable even from a partially
    read number (e.g. 11 of 14 digits). This is the legal source of truth for the
    DOB, far more reliable than reading the printed date.

    Returns None unless the leading digits form a plausible birth date.
    """
    digits = re.sub(r"\D", "", (nid_number or "").translate(_ARABIC_DIGITS))
    if len(digits) < 7:
        return None
    century = {"2": 1900, "3": 2000}.get(digits[0])
    if century is None:
        return None
    try:
        dob = date(century + int(digits[1:3]), int(digits[3:5]), int(digits[5:7]))
    except ValueError:
        return None
    if dob.year < 1920 or dob > date.today():
        return None
    return dob


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

EGYPTIAN NAME STRUCTURE (read carefully — a common source of errors):
Egyptian full names are a CHAIN of given names: <own name> <father's name>
<grandfather's name> <family name>. On the NID the الاسم (name) field is printed
across TWO lines: the FIRST (upper) line is the person's OWN given name (الاسم
الأول), and the SECOND line is the remainder (father, grandfather, family). The
person's full legal name is the FIRST line FOLLOWED BY the second line.
  • You MUST read and combine BOTH lines. Do NOT start the name at the father's
    name — dropping the first line turns the applicant's own name into their
    father's name (e.g. first line "شادى" + second line "جوزيف عبدالملاك بطرس"
    → the full name is "شادى جوزيف عبدالملاك بطرس", NOT "جوزيف عبدالملاك بطرس").
  • When comparing to the form name, the form often supplies only the first 2–3
    parts of this chain. Treat it as a match when the form's parts appear, in the
    same order, as a prefix of the full NID name (allowing transliteration).

IMPORTANT — image orientation: Applicants photograph documents at arbitrary
rotations. A landscape ID card is frequently captured in a portrait frame, so the
card appears rotated 90°, 180°, or 270°, sometimes with slight skew. Orientation
is cosmetic — mentally rotate the image to whatever angle makes the text upright
and read it normally. NEVER report rotation, orientation, or skew as a problem,
and NEVER mark a document invalid or lower confidence merely because it is
rotated. Only the actual content matters (legibility, tampering, expiry, name
match, correct document type).

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
  b) Read the 14-digit NATIONAL ID number (الرقم القومي) — a single horizontal row
     of exactly 14 digits, usually along the lower part of the card. This is NOT
     the short card serial number (a few characters, often with Latin letters such
     as "IW…") — do not confuse the two; nid_number must be the 14-digit number.
     The DOB is encoded in it (digit 1 = century: 2→1900s, 3→2000s; digits 2–7 =
     YYMMDD) and is derived from it automatically, so read all 14 digits carefully.
  c) Read the FULL name across BOTH name lines (own name on the first line +
     father/grandfather/family on the second — see the name-structure note above),
     then check whether it matches "{full_name}" (transliteration equivalence
     applies). Report the complete name in extracted_data, starting with the
     applicant's own first name.
  d) Is the photo clear and unobstructed?
  e) Are there signs of tampering, digital editing, or physical alteration?

NID BACK (بطاقة الرقم القومي / بطاقة تحقيق الشخصية — back):
  a) Is this the back of an Egyptian National ID card? The front (photo side) and
     the back (barcode / data side) are the TWO SIDES OF ONE CARD and naturally
     look different — do NOT treat their differing appearance, layout, or the
     barcode on the back as evidence of two different cards. If the 14-digit
     national number on the back matches the front, that confirms it is the same card.
  b) Are the issue date and expiry date legible? If so, report them in DD/MM/YYYY.
     Flag as invalid only if the card is actually expired.
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

IDENTITY CONSISTENCY (across ALL provided documents):
  a) Do every provided document refer to the SAME individual? Compare the
     person's name across the NID and the police clearance (and professional
     certificate if present), using the full-name and transliteration rules above.
  b) The police clearance name should match the NID name, not just the form. If
     the documents name two different people, this is a serious fraud signal —
     report same_person=false and add a clear issue. If a name is illegible on a
     document, use null and say which document, rather than assuming a match.

Respond ONLY with a JSON object matching this exact schema (no extra text):
{{
  "document_checks": {{
    "nid_front":        {{"valid": true|false|null, "notes": "..."}},
    "nid_back":         {{"valid": true|false|null, "notes": "..."}},
    "police_clearance": {{"valid": true|false|null, "notes": "..."}},
    "professional_cert":{{"valid": true|false|null, "notes": "..."}}
  }},
  "extracted_data": {{
    "nid_number":     "14-digit national number from EITHER side (digits only, NOT the serial), or null",
    "name_on_nid":    "FULL name across both lines (own name first), Arabic, or null",
    "dob_on_nid":     "date of birth from the card in DD/MM/YYYY, or null",
    "address_on_nid": "address as printed on the card, or null",
    "issue_date":     "card ISSUE date (NOT the date of birth) in DD/MM/YYYY, or null",
    "expiry_date":    "card expiry date in DD/MM/YYYY, or null"
  }},
  "name_match":  {{"consistent": true|false|null, "notes": "NID name vs form name"}},
  "age_check":   {{"consistent": true|false|null, "notes": "NID DOB vs form DOB"}},
  "identity_consistency": {{"same_person": true|false|null, "notes": "same individual across all documents?"}},
  "issues":      ["concise description of each problem found — empty if none"],
  "overall_confidence": 0.0
}}

Rules:
- overall_confidence: 0.0 (very suspicious / unreadable) → 1.0 (everything checks out).
- Images may be rotated (90°/180°/270°) or skewed. Rotate them mentally and read
  normally. Do NOT list rotation/orientation/skew as an issue, and do NOT mark a
  document invalid or reduce confidence solely because it is rotated.
- If a document was not provided, set valid to null and notes to "not provided".
- If you cannot read a field clearly, say so in notes rather than guessing.
- extracted_data is a LITERAL OCR transcription of the NID, kept as a record and
  SEPARATE from the validity judgement.
    • CRITICAL: the applicant's form-provided name and DOB at the top of this
      prompt are given ONLY for the name/age comparison. They are NOT the card's
      contents. Transcribe ONLY characters you can actually see on the card.
    • If a field is not clearly legible (blurry, rotated, glare, obscured), set it
      to null. A null is correct and expected — do not fill gaps from the form.
    • NEVER copy the form-provided name or DOB into extracted_data, and NEVER
      derive nid_number from the DOB (or the DOB from a guessed nid_number).
      Echoing the form values as if read from the card is a serious error.
    • nid_number is the national number (الرقم القومي) — a row of digits (14 when
      fully legible), NOT the short card serial (e.g. "IW8931728"). It may be on
      the front and/or the back (data/barcode side); read it from whichever side is
      legible. Read left-to-right from the FIRST digit and report every digit you
      can read with confidence; the leading digits (which encode the DOB) matter
      most. ALWAYS put the digits in extracted_data.nid_number — never only in a
      notes field. Prefer all 14, but a confidently-read partial number beats null.
- The date of birth is derived from the national number, so do NOT raise the
  printed DOB being hard to read as an issue when the number is legible — set
  dob_on_nid to null in that case and move on; it is not a problem to report.
- The NID front (photo side) and back (data/barcode side) look different by design.
  A national number printed only on the back, or a barcode on the back, is NORMAL —
  do NOT treat differing sides as a "mismatched documents" problem. Flag a
  cross-document conflict only for a genuine contradiction (two different names, or
  two different national numbers).
- Apply the same honesty to document_checks notes: do not state a number, name, or
  date is "legible" or "matches" unless you actually read it on the document.
- AVOID FALSE POSITIVES — a "valid" must be earned, never the default:
    • document_checks.valid means the document is authentic AND legible. It is
      about the document itself, so do NOT write "details are consistent/match the
      applicant" in a doc note — that belongs to name_match / identity_consistency.
    • Never assert a positive (valid, consistent, same_person, "matches",
      "verified") for something you did not actually verify. When uncertain or
      illegible, use null and explain — do not round up to true.
    • name_match.consistent and identity_consistency.same_person must be false
      when names genuinely differ, and null (not true) when you cannot read a name.
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
    "name_match": {"consistent": True, "notes": "AI validation disabled"},
    "age_check": {"consistent": True, "notes": "AI validation disabled"},
    "identity_consistency": {"same_person": True, "notes": "AI validation disabled"},
    "extracted_data": {},
    "overall_confidence": 1.0,
}

_SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Anthropic vision model. Opus is the most accurate at reading small / degraded
# text — e.g. the Arabic-Indic digit row and two-line name on an Egyptian NID —
# which is what identity validation hinges on. Accuracy outweighs cost here
# (onboarding is low-volume and asynchronous).
_ANTHROPIC_MODEL = "claude-opus-4-8"

# Cap the longest edge sent to the model. Phone photos are often 3000–4000 px;
# we keep enough resolution for the model to read small ID text (Opus supports up
# to ~2576 px on the long edge) while avoiding wasted image tokens beyond that.
_MAX_IMAGE_DIM = 2576


def _normalize_image(raw: bytes, prefer_landscape: bool = False) -> bytes | None:
    """Bake EXIF orientation into the pixels, optionally rotate to landscape, and
    cap the size.

    Phone cameras record rotation as an EXIF *orientation tag* rather than
    rotating the pixels. Image viewers and browsers honour that tag (so the
    photo looks upright), but a vision model receives the raw pixels — i.e. a
    sideways image it cannot read. Applying the EXIF transform fixes this.

    Many cards carry no EXIF tag yet are still physically rotated (a landscape ID
    card shot in a portrait frame). Vision models read 90°-rotated text poorly and
    tend to confabulate. When ``prefer_landscape`` is set (NID front/back) and the
    image is taller than it is wide, we rotate it to landscape so the card text is
    horizontal — far more legible. Any remaining 180° flip the model handles.

    Returns JPEG bytes, or None if the bytes are not a decodable image (callers
    then fall back to sending the original bytes unchanged).
    """
    try:
        from io import BytesIO

        from PIL import Image, ImageOps

        with Image.open(BytesIO(raw)) as img:
            img = ImageOps.exif_transpose(img)  # rotate pixels per EXIF, drop the tag
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            if prefer_landscape and img.height > img.width:
                # Portrait ID scan → landscape. 90° CCW puts the common
                # phone-capture orientation upright; any 180° flip that remains
                # is easy for the model to read (and is handled in the prompt).
                img = img.rotate(90, expand=True)
            if max(img.size) > _MAX_IMAGE_DIM:
                img.thumbnail((_MAX_IMAGE_DIM, _MAX_IMAGE_DIM), Image.LANCZOS)
            out = BytesIO()
            img.save(out, format="JPEG", quality=90)
            return out.getvalue()
    except Exception:
        logger.warning(
            "ai_validation: image normalization failed; sending original bytes"
        )
        return None


def _encode_file(file_field, *, prefer_landscape: bool = False) -> dict | None:
    """Read a document file and return a base64-encoded payload dict.

    Returns {"mime": <mime_type>, "data": <base64_string>} for images and PDFs.
    Image bytes are orientation-normalized (EXIF + optional landscape rotation for
    ID cards) and size-capped before encoding. Returns None if the file is missing
    or unreadable.
    """
    if not file_field:
        return None
    try:
        path = file_field.path
        mime, _ = mimetypes.guess_type(path)
        if not mime:
            mime = "image/jpeg"
        with open(path, "rb") as f:
            raw = f.read()
    except (FileNotFoundError, OSError, ValueError):
        logger.warning(
            "ai_validation: could not read file %s", getattr(file_field, "name", "?")
        )
        return None

    # PDFs are passed through untouched (native handling by Anthropic/Gemini).
    if mime == "application/pdf":
        return {"mime": mime, "data": base64.standard_b64encode(raw).decode()}

    # Images: normalize orientation so the model sees an upright document.
    normalized = _normalize_image(raw, prefer_landscape=prefer_landscape)
    if normalized is not None:
        return {
            "mime": "image/jpeg",
            "data": base64.standard_b64encode(normalized).decode(),
        }

    # Could not decode as an image — send the original bytes as-is.
    out_mime = mime if mime in _SUPPORTED_IMAGE_TYPES else "image/jpeg"
    return {"mime": out_mime, "data": base64.standard_b64encode(raw).decode()}


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
        "name_match": {"consistent": None, "notes": "validation unavailable"},
        "age_check": {"consistent": None, "notes": "validation unavailable"},
        "identity_consistency": {
            "same_person": None,
            "notes": "validation unavailable",
        },
        "extracted_data": {},
        "overall_confidence": 0.5,
    }


def _apply_nid_dob_decode(report: dict, form_dob: str) -> None:
    """Overwrite the DOB and age check using the 14-digit national ID number.

    When the model has read a valid 14-digit number, the DOB it encodes is the
    source of truth, so we derive it in code and compare it to the form DOB. This
    removes a whole class of date-reading errors. No-op if the number is missing
    or not 14 digits (the model's read values then stand).
    """
    extracted = report.get("extracted_data")
    if not isinstance(extracted, dict):
        return
    decoded = decode_nid_dob(str(extracted.get("nid_number") or "").strip())
    if not decoded:
        return
    dob_str = decoded.strftime("%d/%m/%Y")
    extracted["dob_on_nid"] = dob_str
    matches = dob_str == (form_dob or "").strip()
    report["age_check"] = {
        "consistent": matches,
        "notes": (
            f"DOB {dob_str} decoded from the national ID number; "
            + ("matches the form." if matches else f"form shows {form_dob} — mismatch.")
        ),
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

    model_id = _ANTHROPIC_MODEL
    t_start = time.monotonic()
    message = client.messages.create(
        model=model_id,
        max_tokens=2048,  # headroom so the JSON report is never truncated
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    latency_ms = int((time.monotonic() - t_start) * 1000)
    # Take the first text block (robust to any non-text blocks the model emits).
    raw = next((b.text for b in message.content if b.type == "text"), "").strip()
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
        # NID cards are landscape; rotate portrait scans so the model can read them.
        block = _encode_file(field, prefer_landscape=label in ("nid_front", "nid_back"))
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

                # The 14-digit national ID number is the authoritative source for
                # the DOB — decode it in code rather than trusting the read date.
                _apply_nid_dob_decode(report, applicant_snapshot["dob"])

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

                # Identity red flags are never allowed to "pass": a name/age
                # mismatch or documents belonging to different people must surface.
                name_match = report.get("name_match") or {}
                identity = report.get("identity_consistency") or {}
                age_check = report.get("age_check") or {}
                identity_mismatch = (
                    name_match.get("consistent") is False
                    or identity.get("same_person") is False
                    or age_check.get("consistent") is False
                )

                if (any_invalid or identity_mismatch) and confidence < 0.4:
                    status = "failed"
                elif any_invalid or identity_mismatch or issues or confidence < 0.5:
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
