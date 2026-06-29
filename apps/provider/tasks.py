"""
Celery tasks for provider onboarding.

  validate_onboarding_documents  — runs AI validation after a provider submits
  notify_resubmit_available      — daily beat task: FCM reminder when rejection cooldown lifts
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


def _mark_flagged(onboarding_id: str, reason: str) -> None:
    """Write a FLAGGED result to the DB and the audit log — used as a last resort."""
    from apps.provider.ai_validation import _write_log
    from apps.provider.choices import AIValidationStatus
    from apps.provider.models import ProviderOnboarding

    report = {
        "status": "flagged",
        "issues": [reason],
        "overall_confidence": 0.5,
    }
    try:
        onboarding = ProviderOnboarding.objects.filter(pk=onboarding_id).first()
        if onboarding:
            onboarding.ai_validation_status = AIValidationStatus.FLAGGED
            onboarding.ai_validation_report = report
            onboarding.save(
                update_fields=["ai_validation_status", "ai_validation_report"]
            )
        _write_log(
            onboarding,
            outcome="error",
            applicant_snapshot=(
                {
                    "full_name": onboarding.get_full_name(),
                    "dob": str(onboarding.date_of_birth),
                    "phone": onboarding.phone,
                }
                if onboarding
                else {}
            ),
            documents_sent=[],
            parsed_report=report,
            error_message=reason,
        )
    except Exception:
        logger.exception("_mark_flagged: could not update onboarding %s", onboarding_id)


@shared_task(
    bind=True,
    max_retries=2,
    acks_late=True,
    reject_on_worker_lost=True,
)
def validate_onboarding_documents(self, onboarding_id: str) -> None:
    """
    Run Claude Vision validation on an onboarding application's documents.

    Sets ai_validation_status to RUNNING while processing, then updates it
    to the result (passed / flagged / failed) with the full report JSON.

    Retries up to 2 times (3 total attempts) with exponential back-off.
    If all retries are exhausted the status is set to FLAGGED so the
    application still surfaces for manual review instead of silently stalling.
    """
    from apps.provider.ai_validation import validate_onboarding
    from apps.provider.choices import AIValidationStatus
    from apps.provider.models import ProviderOnboarding

    try:
        onboarding = ProviderOnboarding.objects.get(pk=onboarding_id)
    except ProviderOnboarding.DoesNotExist:
        logger.error(
            "validate_onboarding_documents: onboarding %s not found", onboarding_id
        )
        return

    onboarding.ai_validation_status = AIValidationStatus.RUNNING
    onboarding.save(update_fields=["ai_validation_status"])

    # validate_onboarding() catches all its own errors and always returns a dict.
    # This guard handles unexpected bugs that slip through and provides
    # retry-with-backoff for any future code paths that do raise.
    try:
        report = validate_onboarding(onboarding)
    except Exception as exc:
        logger.exception(
            "validate_onboarding_documents: unexpected error for %s (attempt %s/%s)",
            onboarding_id,
            self.request.retries + 1,
            self.max_retries + 1,
        )
        if self.request.retries >= self.max_retries:
            _mark_flagged(
                onboarding_id,
                "AI validation failed after max retries — manual review required",
            )
            return
        raise self.retry(exc=exc, countdown=60 * 2**self.request.retries) from exc

    raw_status = report.get("status", "flagged")
    ai_status_map = {
        "passed": AIValidationStatus.PASSED,
        "flagged": AIValidationStatus.FLAGGED,
        "failed": AIValidationStatus.FAILED,
    }
    onboarding.ai_validation_status = ai_status_map.get(
        raw_status, AIValidationStatus.FLAGGED
    )
    onboarding.ai_validation_report = report
    extracted = report.get("extracted_data")
    onboarding.nid_extracted_data = extracted if isinstance(extracted, dict) else {}
    onboarding.save(
        update_fields=[
            "ai_validation_status",
            "ai_validation_report",
            "nid_extracted_data",
        ]
    )

    logger.info(
        "validate_onboarding_documents: %s → %s (confidence=%.2f)",
        onboarding_id,
        raw_status,
        report.get("overall_confidence", 0),
    )


@shared_task
def notify_resubmit_available() -> None:
    """
    Daily beat task: send an FCM reminder to providers whose rejection cooldown
    just expired (within the last 24 hours). Cooldown duration is set via
    Constance → ONBOARDING_REJECTION_COOLDOWN_DAYS.
    """
    from datetime import timedelta

    from apps.notifications.service import notify_provider_resubmit_available
    from apps.provider.choices import OnboardingStatus
    from apps.provider.models import ProviderOnboarding

    now = timezone.now()
    window_start = now - timedelta(hours=24)

    newly_eligible = ProviderOnboarding.objects.filter(
        status=OnboardingStatus.REJECTED,
        can_resubmit_after__gte=window_start,
        can_resubmit_after__lte=now,
        applicant__isnull=False,
    ).select_related("applicant")

    count = 0
    for app in newly_eligible:
        try:
            notify_provider_resubmit_available(app.applicant)
            count += 1
        except Exception:
            logger.exception(
                "notify_resubmit_available: failed to notify provider %s",
                app.applicant_id,
            )

    logger.info("notify_resubmit_available: notified %d provider(s)", count)
