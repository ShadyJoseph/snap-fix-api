#!/usr/bin/env python
"""
Standalone end-to-end smoke test for the provider-onboarding AI document validation.

This is a **developer script**, deliberately NOT a Django management command, so it
is never part of the shipped command surface and cannot be wired into a deployment
entrypoint by accident.

It makes a **real** call to the configured AI provider using:
  • the API key(s) from your environment / .env (read by Django settings), and
  • the real identity documents in the local ``test-data/`` folder.

It builds a throwaway ``ProviderOnboarding`` with those documents attached, runs
the actual ``validate_onboarding()`` pipeline synchronously (the same code the
Celery task runs after a provider submits), prints a detailed report, and then
deletes the throwaway data (unless ``--keep``).

Run it inside the stack so Redis/Constance and the API keys are available:

    docker compose exec web python scripts/e2e_onboarding.py
    docker compose exec web python scripts/e2e_onboarding.py --provider anthropic --keep
    docker compose exec web python scripts/e2e_onboarding.py --name "شادى جوزيف" --dob 21/07/1995

Note: this spends real API tokens. ``test-data/`` is gitignored — supply your own.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Django bootstrap (must happen before importing anything Django) ────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

# Arabic NID names and box-drawing glyphs are printed below — make sure stdout can
# encode them regardless of the container/terminal locale.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from django.conf import settings  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402

PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

# How we recognise each document inside the test-data folder (case-insensitive
# substrings tried in order). professional_cert is optional.
DOC_MATCHERS = {
    "nid_front": ["front"],
    "nid_back": ["back"],
    "police_clearance_certificate": ["police", "clearance"],
    "professional_certificate": ["professional", "prof_cert", "certificate"],
}

# ── Tiny output helpers ────────────────────────────────────────────────────────
_TTY = sys.stdout.isatty()


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _TTY else str(text)


def bold(t):
    return _c("1", t)


def green(t):
    return _c("32", t)


def red(t):
    return _c("31", t)


def yellow(t):
    return _c("33", t)


def blue(t):
    return _c("36", t)


def dim(t):
    return _c("2", t)


def hr(char="─", width=72):
    print(dim(char * width))


def section(title):
    print()
    hr("━")
    print(bold(title))
    hr("━")


def kv(label, value, width=18):
    print(f"  {label:<{width}} {value}")


def tri(value, true_icon="✔", false_icon="✘", none_icon="—"):
    """Coloured tri-state marker for True / False / None."""
    if value is True:
        return green(true_icon)
    if value is False:
        return red(false_icon)
    return dim(none_icon)


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> int:
    args = _parse_args()

    print()
    print(bold(blue("╔══ SnapFix · Onboarding AI validation · E2E smoke test ══╗")))
    kv("Run at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    kv("Provider", args.provider)
    kv("Data dir", args.data_dir)
    kv("DEBUG", settings.DEBUG)

    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        print(red(f"\nERROR: document folder not found: {data_dir}"))
        print("Put your test images in test-data/ (or pass --data-dir).")
        return 1

    if not _check_keys(args.provider):
        return 1

    docs = _discover_documents(data_dir)
    if docs is None:
        return 1

    onboarding, applicant = _build_onboarding(args, docs)

    section("Running AI validation (real API call)…")
    print(dim(f"  Sending {len(docs)} document(s) to '{args.provider}'…"))
    report, elapsed = _run_validation(onboarding, args.provider)

    _print_verdict(report, elapsed)
    _print_form_vs_card(args, report)
    _print_consistency(report)
    _print_extracted(report)
    _print_doc_checks(report)
    _print_issues(report)

    log = _latest_log(onboarding)
    _print_call_metadata(log)
    _print_raw(log)

    section("Cleanup")
    if args.keep:
        _persist(onboarding, report)
        print(
            yellow(
                f"  --keep set; onboarding {onboarding.pk} saved — inspect it in the admin."
            )
        )
    else:
        _cleanup(onboarding, applicant, docs)
        print(green("  Deleted throwaway records and files."))
    print()
    return 0


def _parse_args():
    p = argparse.ArgumentParser(
        description="Real E2E test of the onboarding AI validation."
    )
    p.add_argument(
        "--provider",
        default="all",
        choices=["all", "anthropic", "openai", "groq", "gemini"],
        help="Which AI provider to force for this run (default: all → cascade).",
    )
    p.add_argument(
        "--data-dir",
        default=str(ROOT / "test-data"),
        help="Folder holding the document images (default: <repo>/test-data).",
    )
    p.add_argument(
        "--name", default="Ahmed Mohamed Ali", help="Applicant full name on the form."
    )
    p.add_argument("--dob", default="15/06/1995", help="Date of birth DD/MM/YYYY.")
    p.add_argument("--phone", default="01012345678", help="Applicant phone.")
    p.add_argument(
        "--keep",
        action="store_true",
        help="Keep the throwaway onboarding (with the report saved) instead of deleting it.",
    )
    return p.parse_args()


# ── Pre-flight ─────────────────────────────────────────────────────────────────


def _check_keys(provider) -> bool:
    section("API keys (from environment)")
    needed = list(PROVIDER_KEYS) if provider == "all" else [provider]
    any_missing = False
    for name, var in PROVIDER_KEYS.items():
        key = getattr(settings, var, "") or ""
        tail = f"set (…{key[-4:]})" if key else "not set"
        print(f"  {tri(bool(key))} {var:<20} {tail}")
        if name in needed and not key:
            any_missing = True

    if any_missing and provider != "all":
        print(
            red(
                f"\nERROR: {PROVIDER_KEYS[provider]} is not set — cannot call '{provider}'."
            )
        )
        return False
    if any_missing and provider == "all":
        print(yellow("  Some keys are unset; the cascade will skip those providers."))
    return True


def _discover_documents(data_dir):
    files = sorted(
        p for p in data_dir.iterdir() if p.is_file() and not p.name.startswith(".")
    )
    if not files:
        print(red(f"\nERROR: no files found in {data_dir}."))
        return None

    resolved, used = {}, set()
    for field, needles in DOC_MATCHERS.items():
        for needle in needles:
            match = next(
                (f for f in files if needle in f.name.lower() and f not in used), None
            )
            if match:
                resolved[field] = match
                used.add(match)
                break

    section("Documents discovered")
    for field in DOC_MATCHERS:
        path = resolved.get(field)
        if not path:
            print(f"  {dim('—')} {field:<32} {dim('(none)')}")
            continue
        info = _image_info(path)
        print(f"  {green('✓')} {field:<32} {path.name}  {dim(info)}")

    if "nid_front" not in resolved or "nid_back" not in resolved:
        print(red("\nERROR: could not find NID front/back images."))
        print(f"Files present: {[f.name for f in files]}")
        print("Expected filenames containing 'front' and 'back'.")
        return None
    return resolved


def _image_info(path: Path) -> str:
    size_kb = path.stat().st_size / 1024
    try:
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
        shape = "portrait" if h > w else "landscape"
        is_nid = any(n in path.name.lower() for n in ("front", "back"))
        rot = " → will auto-rotate to landscape" if (is_nid and h > w) else ""
        return f"{w}×{h} {shape}, {size_kb:.0f} KB{rot}"
    except Exception:
        return f"{size_kb:.0f} KB"


# ── Build / run ────────────────────────────────────────────────────────────────


def _build_onboarding(args, docs):
    from apps.provider.choices import OnboardingStatus
    from apps.provider.models import Provider, ProviderOnboarding
    from factories import make_category, make_region

    parts = args.name.split(" ", 1)
    first, last = parts[0], (parts[1] if len(parts) > 1 else "Applicant")
    try:
        dob = datetime.strptime(args.dob, "%d/%m/%Y").date()
    except ValueError:
        print(red(f"\nERROR: --dob must be DD/MM/YYYY, got '{args.dob}'."))
        sys.exit(1)

    region = make_region(name="E2E Region", slug="e2e-region", code="E2E")
    category = make_category(name="E2E Plumbing", slug="e2e-plumbing")
    email = f"e2e_{int(time.time())}@e2e.local"
    applicant = Provider.objects.create_user(
        email=email,
        first_name=first,
        last_name=last,
        phone=args.phone,
        password="e2e-throwaway-pass",
        is_active=False,
    )

    file_kwargs = {
        field: SimpleUploadedFile(
            path.name, path.read_bytes(), content_type=_ctype(path)
        )
        for field, path in docs.items()
    }
    onboarding = ProviderOnboarding(
        region=region,
        category=category,
        applicant=applicant,
        first_name=first,
        last_name=last,
        email=email,
        phone=args.phone,
        date_of_birth=dob,
        address="1 E2E Street, Cairo",
        hourly_rate="150.00",
        years_of_experience=3,
        status=OnboardingStatus.PENDING,
        **file_kwargs,
    )
    onboarding.save()

    section("Applicant under test (form data)")
    kv("Name", args.name)
    kv("Date of birth", args.dob)
    kv("Phone", args.phone)
    kv("Onboarding id", onboarding.pk)
    return onboarding, applicant


def _run_validation(onboarding, provider):
    from constance import config

    from apps.provider.ai_validation import validate_onboarding

    prev_enabled = config.AI_VALIDATION_ENABLED
    prev_provider = config.AI_VALIDATION_PROVIDER
    config.AI_VALIDATION_ENABLED = True
    config.AI_VALIDATION_PROVIDER = provider
    try:
        t0 = time.monotonic()
        report = validate_onboarding(onboarding)
        elapsed = time.monotonic() - t0
    finally:
        config.AI_VALIDATION_ENABLED = prev_enabled
        config.AI_VALIDATION_PROVIDER = prev_provider
    return report, elapsed


# ── Output ─────────────────────────────────────────────────────────────────────


def _print_verdict(report, elapsed):
    status = (report.get("status") or "?").upper()
    colour = {"PASSED": green, "FLAGGED": yellow, "FAILED": red}.get(status, blue)
    section("Verdict")
    print(f"  {colour(bold(f'  {status}  '))}   in {elapsed:.1f}s")
    conf = report.get("overall_confidence")
    if isinstance(conf, int | float):
        bar = "█" * round(conf * 20)
        kv("Confidence", f"{conf:.0%}  {dim(bar)}")


def _print_form_vs_card(args, report):
    extracted = report.get("extracted_data") or {}
    section("Form vs NID card")
    print(f"  {'':<14} {'FORM':<28} {'NID CARD (OCR)'}")
    print(
        f"  {'Name':<14} {str(args.name):<28} {extracted.get('name_on_nid') or dim('—')}"
    )
    print(
        f"  {'Date of birth':<14} {str(args.dob):<28} {extracted.get('dob_on_nid') or dim('—')}"
    )


def _print_consistency(report):
    section("Consistency checks")
    specs = [
        ("Name match (NID vs form)", report.get("name_match"), "consistent"),
        ("Age check  (NID vs form)", report.get("age_check"), "consistent"),
        ("Same person across docs ", report.get("identity_consistency"), "same_person"),
    ]
    for label, data, key in specs:
        data = data if isinstance(data, dict) else {}
        print(f"  {tri(data.get(key))} {label}  {dim(data.get('notes', ''))}")


def _print_extracted(report):
    extracted = report.get("extracted_data") or {}
    section("Extracted NID data (OCR)")
    if not any(extracted.values()):
        print(dim("  (nothing legible)"))
        return
    for key, label in (
        ("nid_number", "NID number"),
        ("name_on_nid", "Name on NID"),
        ("dob_on_nid", "Date of birth"),
        ("address_on_nid", "Address"),
        ("issue_date", "Issue date"),
        ("expiry_date", "Expiry date"),
    ):
        kv(label, extracted.get(key) or dim("—"))


def _print_doc_checks(report):
    section("Document checks")
    labels = {
        "nid_front": "NID front",
        "nid_back": "NID back",
        "police_clearance": "Police clearance",
        "professional_cert": "Professional cert",
    }
    checks = report.get("document_checks") or {}
    for key, label in labels.items():
        c = checks.get(key) or {}
        print(f"  {tri(c.get('valid'))} {label:<18} {dim(c.get('notes', ''))}")


def _print_issues(report):
    issues = report.get("issues") or []
    section(f"Issues ({len(issues)})")
    if not issues:
        print(green("  None."))
        return
    for issue in issues:
        print(f"  {red('•')} {issue}")


def _latest_log(onboarding):
    from apps.provider.models import AIValidationLog

    return (
        AIValidationLog.objects.filter(onboarding=onboarding)
        .order_by("-triggered_at")
        .first()
    )


def _print_call_metadata(log):
    if not log:
        return
    section("AI call metadata")
    kv("Outcome", log.outcome)
    kv("Model", log.model_id or "—")
    kv("Latency", f"{log.latency_ms or '—'} ms")
    kv(
        "Tokens",
        f"in={log.input_tokens or '—'}  out={log.output_tokens or '—'}  total={log.total_tokens or '—'}",
    )
    if log.error_message:
        print(red(f"  Error: {log.error_message}"))


def _print_raw(log):
    if not log or not log.raw_response:
        return
    section("Raw model response (truncated)")
    preview = log.raw_response.strip()
    print(dim(preview[:600] + ("…" if len(preview) > 600 else "")))


# ── Persistence / cleanup ──────────────────────────────────────────────────────


def _persist(onboarding, report):
    from apps.provider.choices import AIValidationStatus

    status_map = {
        "passed": AIValidationStatus.PASSED,
        "flagged": AIValidationStatus.FLAGGED,
        "failed": AIValidationStatus.FAILED,
    }
    extracted = report.get("extracted_data")
    onboarding.ai_validation_status = status_map.get(
        report.get("status"), AIValidationStatus.FLAGGED
    )
    onboarding.ai_validation_report = report
    onboarding.nid_extracted_data = extracted if isinstance(extracted, dict) else {}
    onboarding.save(
        update_fields=[
            "ai_validation_status",
            "ai_validation_report",
            "nid_extracted_data",
        ]
    )


def _cleanup(onboarding, applicant, docs):
    for field in docs:
        f = getattr(onboarding, field, None)
        if f:
            f.delete(save=False)
    onboarding.delete()
    if applicant:
        applicant.delete()


def _ctype(path: Path) -> str:
    import mimetypes

    return mimetypes.guess_type(path.name)[0] or "image/jpeg"


if __name__ == "__main__":
    raise SystemExit(main())
