"""
AI-powered provider recommendation reasoning.

Mirrors apps/provider/ai_validation.py in architecture:
  - Same multi-provider registry (OpenAI, Gemini, Groq, Anthropic)
  - Same Constance runtime config (AI_RECOMMENDATION_ENABLED, AI_RECOMMENDATION_PROVIDER)
  - Same _is_transient() / retry / fallback / _clean_json() pattern
  - Never raises — every error path returns a generic reason string

Entry point
-----------
  generate_recommendation_reasons(scored_providers, category_name, is_urgent)
    → dict[str, str]   # {str(provider.pk): reason_sentence}

The caller passes the full scored_providers list (output of get_top_providers)
so the AI receives every signal per candidate and can reason about trade-offs.
"""

from __future__ import annotations

import json
import logging
import re
import time

from constance import config
from django.conf import settings

from .choices import AIRecommendationOutcome

logger = logging.getLogger(__name__)


# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a provider-matching assistant for a home-services platform.
Your job is to write one concise, friendly sentence explaining why each
candidate provider is a good fit for the customer's service request.
Base your explanations on the numerical signals provided — do not invent facts.
Write from the customer's perspective. Keep each sentence under 20 words.
"""


def _build_prompt(
    scored_providers: list[dict], category_name: str, is_urgent: bool
) -> str:
    lines = [
        f"The customer needs: {category_name}.",
        f"Urgent request: {'yes' if is_urgent else 'no'}.",
        "",
        "Candidate providers with match signals (score 0-100, higher is better):",
        "",
    ]

    for i, item in enumerate(scored_providers, 1):
        p = item["provider"]
        s = item["signals"]
        full_name = p.get_full_name()
        business = p.business_name or full_name
        acceptance = p.acceptance_rate
        acceptance_str = f"{acceptance * 100:.0f}%" if acceptance is not None else "N/A"
        lines += [
            f"Provider {i} – {full_name} ({business})",
            f"  rating_score:           {s['rating']} / 100  ({float(p.average_rating):.1f}★, {p.total_reviews} reviews)",
            f"  distance_score:         {s['distance']} / 100  ({item['distance_km']} km away)",
            f"  completion_rate_score:  {s['completion_rate']} / 100  ({p.get_completion_rate() if p.total_jobs > 0 else 'N/A'}% of jobs completed)",
            f"  is_customer_favourite:  {item['is_favorite']}",
            f"  urgency_avail_score:    {s['urgency_availability']} / 100  (available now: {p.is_available})",
            f"  hourly_rate:            {p.hourly_rate or 'not set'}",
            f"  years_experience:       {p.years_of_experience}",
            f"  acceptance_rate:        {acceptance_str}",
            f"  FINAL SCORE:            {item['score']}",
            "",
        ]

    lines += [
        "Write one sentence per provider explaining why they are a good fit.",
        "Return JSON only, no extra text:",
        "{",
    ]
    for item in scored_providers:
        lines.append(f'  "{item["provider"].pk}": "<reason>",')
    lines.append("}")

    return "\n".join(lines)


# ── Fallback ───────────────────────────────────────────────────────────────────


def _generic_reasons(scored_providers: list[dict]) -> dict[str, str]:
    """
    Rule-based fallback reasons derived entirely from the scoring signals.

    Highlights the strongest dimensions for each provider so the output is
    still meaningful without any AI call — used when AI is disabled, all
    API keys are missing, or every provider in the cascade has failed.
    """
    result = {}
    for item in scored_providers:
        p = item["provider"]
        s = item["signals"]
        parts = []

        # Favourite status leads because it is a strong personal signal.
        if item["is_favorite"]:
            parts.append("one of your favorites")

        # Rating — only call out explicitly strong ratings.
        rating = float(p.average_rating)
        if s["rating"] >= 70:
            parts.append(f"highly rated at {rating:.1f}★")
        else:
            parts.append(f"rated {rating:.1f}★")

        # Distance — only mention when the signal actually contributes.
        dist = item["distance_km"]
        if s["distance"] >= 70:
            parts.append(f"very close ({dist} km away)")
        elif s["distance"] >= 30:
            parts.append(f"{dist} km away")

        # Completion rate — only highlight reliable providers.
        if p.total_jobs > 0:
            cr = p.get_completion_rate()
            if cr >= 80:
                parts.append(f"{cr:.0f}% completion rate")

        # Urgency availability — only when fully available for an urgent job.
        if s["urgency_availability"] == 100.0:
            parts.append("available now")

        sentence = ", ".join(parts)
        result[str(p.pk)] = sentence[0].upper() + sentence[1:] + "."

    return result


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


def _clean_json(raw: str) -> dict:
    """Strip markdown code fences from model output and parse JSON."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```\w*\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned.strip())


# ── Provider adapters ──────────────────────────────────────────────────────────
# Each adapter receives (system_prompt, user_prompt) and returns the raw text.


def _call_openai(system: str, prompt: str) -> str:
    from openai import OpenAI

    api_key = getattr(settings, "OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = OpenAI(api_key=api_key)
    model_id = "gpt-4o-mini"
    t0 = time.monotonic()
    response = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=512,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.debug("ai_recommendation: openai latency=%dms", latency_ms)
    return response.choices[0].message.content


def _call_groq(system: str, prompt: str) -> str:
    from groq import Groq

    api_key = getattr(settings, "GROQ_API_KEY", "")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set")
    client = Groq(api_key=api_key)
    model_id = "meta-llama/llama-4-scout-17b-16e-instruct"
    t0 = time.monotonic()
    response = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=512,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.debug("ai_recommendation: groq latency=%dms", latency_ms)
    return response.choices[0].message.content


def _call_gemini(system: str, prompt: str) -> str:
    import google.generativeai as genai

    api_key = getattr(settings, "GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    model_id = "gemini-2.0-flash"
    model = genai.GenerativeModel(model_id, system_instruction=system)
    t0 = time.monotonic()
    response = model.generate_content(
        prompt, generation_config={"response_mime_type": "application/json"}
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.debug("ai_recommendation: gemini latency=%dms", latency_ms)
    return response.text


def _call_anthropic(system: str, prompt: str) -> str:
    import anthropic

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)
    model_id = "claude-haiku-4-5-20251001"
    t0 = time.monotonic()
    message = client.messages.create(
        model=model_id,
        max_tokens=512,
        system=system,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "{"},
        ],
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.debug("ai_recommendation: anthropic latency=%dms", latency_ms)
    return "{" + message.content[0].text.strip()


_PROVIDERS = {
    "openai": _call_openai,
    "gemini": _call_gemini,
    "groq": _call_groq,
    "anthropic": _call_anthropic,
}

_MODEL_IDS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "groq": "meta-llama/llama-4-scout-17b-16e-instruct",
    "anthropic": "claude-haiku-4-5-20251001",
}


def _write_log(
    *,
    service_request=None,
    category_name: str,
    is_urgent: bool,
    candidate_snapshot: list,
    outcome: str,
    raw_response: str = "",
    parsed_reasons: dict | None = None,
    error_message: str = "",
    model_id: str = "",
    latency_ms: int | None = None,
) -> None:
    try:
        from .models import AIRecommendationLog

        AIRecommendationLog.objects.create(
            service_request=service_request,
            category_name=category_name,
            is_urgent=is_urgent,
            candidate_snapshot=candidate_snapshot,
            outcome=outcome,
            raw_response=raw_response,
            parsed_reasons=parsed_reasons or {},
            error_message=error_message,
            model_id=model_id,
            latency_ms=latency_ms,
        )
    except Exception:
        logger.exception("ai_recommendation: failed to write AIRecommendationLog")


def _build_candidate_snapshot(scored_providers: list[dict]) -> list:
    return [
        {
            "provider_id": str(item["provider"].pk),
            "name": item["provider"].get_full_name(),
            "score": item["score"],
            "signals": item["signals"],
            "distance_km": item["distance_km"],
            "is_favorite": item["is_favorite"],
        }
        for item in scored_providers
    ]


# ── Entry point ────────────────────────────────────────────────────────────────


def generate_recommendation_reasons(
    scored_providers: list[dict],
    category_name: str,
    is_urgent: bool,
    service_request=None,
) -> dict[str, str]:
    """
    Call the configured AI provider(s) to generate a one-sentence recommendation
    reason for each provider in `scored_providers`.

    Returns {str(provider.pk): reason_sentence}.  Never raises — falls back to
    plain-text reasons derived from signal scores when all providers fail.

    Feature flag: AI_RECOMMENDATION_ENABLED in Constance.
    Provider:     AI_RECOMMENDATION_PROVIDER in Constance (openai/groq/gemini/anthropic/all).

    Writes an AIRecommendationLog row for every call (including bypasses and errors).
    Pass the saved ServiceRequest instance if available so the log can be linked.
    """
    if not scored_providers:
        return {}

    candidate_snapshot = _build_candidate_snapshot(scored_providers)

    if not getattr(config, "AI_RECOMMENDATION_ENABLED", True):
        logger.info(
            "ai_recommendation: disabled via Constance flag — returning generic reasons"
        )
        reasons = _generic_reasons(scored_providers)
        _write_log(
            service_request=service_request,
            category_name=category_name,
            is_urgent=is_urgent,
            candidate_snapshot=candidate_snapshot,
            outcome=AIRecommendationOutcome.BYPASSED,
            parsed_reasons=reasons,
        )
        return reasons

    prompt = _build_prompt(scored_providers, category_name, is_urgent)

    provider_setting = getattr(config, "AI_RECOMMENDATION_PROVIDER", "all")
    if not isinstance(provider_setting, str):
        provider_setting = "all"
    provider_setting = provider_setting.lower()

    if provider_setting == "all":
        provider_list = ["openai", "gemini", "groq", "anthropic"]
    elif provider_setting in _PROVIDERS:
        provider_list = [provider_setting]
    else:
        logger.warning(
            "ai_recommendation: unknown provider '%s', falling back to 'all'",
            provider_setting,
        )
        provider_list = ["openai", "gemini", "groq", "anthropic"]

    for provider_name in provider_list:
        provider_fn = _PROVIDERS[provider_name]
        model_id = _MODEL_IDS.get(provider_name, "")

        last_exc: Exception | None = None
        for attempt in range(3):
            t0 = time.monotonic()
            try:
                raw = provider_fn(_SYSTEM_PROMPT, prompt)
                latency_ms = int((time.monotonic() - t0) * 1000)
                parsed = _clean_json(raw)

                if not isinstance(parsed, dict):
                    raise ValueError(
                        f"{provider_name} returned {type(parsed).__name__}, expected object"
                    )

                # Fill in any missing keys with generic reasons.
                reasons = {}
                for item in scored_providers:
                    key = str(item["provider"].pk)
                    reasons[key] = parsed.get(key) or _generic_reasons([item])[key]

                _write_log(
                    service_request=service_request,
                    category_name=category_name,
                    is_urgent=is_urgent,
                    candidate_snapshot=candidate_snapshot,
                    outcome=AIRecommendationOutcome.SUCCESS,
                    raw_response=raw,
                    parsed_reasons=reasons,
                    model_id=model_id,
                    latency_ms=latency_ms,
                )
                return reasons

            except Exception as exc:
                latency_ms = int((time.monotonic() - t0) * 1000)
                if _is_transient(exc):
                    last_exc = exc
                    logger.warning(
                        "ai_recommendation: %s attempt %d/3 transient error: %s",
                        provider_name,
                        attempt + 1,
                        exc,
                    )
                    if attempt < 2:
                        time.sleep(2**attempt)
                else:
                    logger.error(
                        "ai_recommendation: %s failed (non-transient): %s",
                        provider_name,
                        exc,
                    )
                    _write_log(
                        service_request=service_request,
                        category_name=category_name,
                        is_urgent=is_urgent,
                        candidate_snapshot=candidate_snapshot,
                        outcome=AIRecommendationOutcome.ERROR,
                        error_message=f"{provider_name}: {exc}",
                        model_id=model_id,
                        latency_ms=latency_ms,
                    )
                    break
        else:
            # All 3 transient attempts exhausted — log before trying next provider.
            _write_log(
                service_request=service_request,
                category_name=category_name,
                is_urgent=is_urgent,
                candidate_snapshot=candidate_snapshot,
                outcome=AIRecommendationOutcome.ERROR,
                error_message=f"{provider_name}: transient error after 3 attempts — {last_exc}",
                model_id=model_id,
            )

    logger.warning(
        "ai_recommendation: all providers failed — returning generic reasons"
    )
    reasons = _generic_reasons(scored_providers)
    _write_log(
        service_request=service_request,
        category_name=category_name,
        is_urgent=is_urgent,
        candidate_snapshot=candidate_snapshot,
        outcome=AIRecommendationOutcome.FALLBACK,
        parsed_reasons=reasons,
        error_message="All AI providers exhausted — using generic reasons",
    )
    return reasons
