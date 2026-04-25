"""
Notification service — single entry point for all notification dispatch.

Flow for every event:
  1. Persist a Notification row synchronously (the in-app inbox entry).
  2. Enqueue a Celery task that sends the FCM push asynchronously.

Keeping step 1 synchronous guarantees the inbox is always up-to-date even
if the Celery worker is temporarily down. The push is best-effort with
automatic retries.
"""

import logging

from django.db import transaction

from .choices import NotificationType
from .models import Notification

logger = logging.getLogger(__name__)

# ── Core dispatcher ────────────────────────────────────────────────────────────


def notify(
    recipient,
    notification_type: NotificationType,
    title: str,
    body: str,
    data: dict | None = None,
):
    """
    Persist the notification to the DB, then enqueue an async FCM push.
    Returns the saved Notification instance.

    The FCM enqueue is fire-and-forget: if the broker (Redis) is temporarily
    unavailable the inbox row is still saved and the push is simply skipped
    with a warning rather than raising into the caller's HTTP response.
    """
    from .tasks import send_push_notification

    data = data or {}
    # Always include the notification type so the mobile app can route without
    # an extra API call.
    fcm_data = {**data, "type": notification_type}

    notification = Notification.objects.create(
        recipient=recipient,
        type=notification_type,
        title=title,
        body=body,
        data=data,
    )

    # Enqueue after the current transaction commits so the task is never
    # dispatched for a booking state that rolled back.
    def _enqueue():
        try:
            send_push_notification.delay(str(recipient.pk), title, body, fcm_data)
        except Exception:
            logger.warning(
                "Could not enqueue FCM push for user %s (notification %s saved). "
                "Is the Celery broker reachable?",
                recipient.pk,
                notification.pk,
            )

    transaction.on_commit(_enqueue)

    return notification


# ── Per-event helpers ──────────────────────────────────────────────────────────


def notify_customer_request_assigned(sr):
    """pending → assigned."""
    notify(
        recipient=sr.customer,
        notification_type=NotificationType.REQUEST_ASSIGNED,
        title="Provider Assigned",
        body=f"{sr.provider.get_full_name()} has been assigned to your request «{sr.title}».",
        data={"service_request_id": str(sr.id)},
    )


def notify_customer_quote_received(sr):
    """assigned → quoted."""
    notify(
        recipient=sr.customer,
        notification_type=NotificationType.QUOTE_RECEIVED,
        title="New Quote",
        body=f"You received a quote of {sr.quoted_price} for «{sr.title}». Tap to review.",
        data={"service_request_id": str(sr.id)},
    )


def notify_customer_request_accepted(sr):
    """assigned → confirmed (provider accepted directly, no quote)."""
    notify(
        recipient=sr.customer,
        notification_type=NotificationType.REQUEST_ACCEPTED,
        title="Request Accepted",
        body=f"{sr.provider.get_full_name()} accepted your request «{sr.title}».",
        data={"service_request_id": str(sr.id)},
    )


def notify_customer_job_started(sr):
    """confirmed → in_progress."""
    notify(
        recipient=sr.customer,
        notification_type=NotificationType.JOB_STARTED,
        title="Job Started",
        body=f"{sr.provider.get_full_name()} has started working on «{sr.title}».",
        data={"service_request_id": str(sr.id)},
    )


def notify_customer_job_completed(sr):
    """in_progress → completed."""
    notify(
        recipient=sr.customer,
        notification_type=NotificationType.JOB_COMPLETED,
        title="Job Completed",
        body=f"Your request «{sr.title}» is done. Tap to leave a review.",
        data={"service_request_id": str(sr.id)},
    )


def notify_customer_request_declined(sr):
    """assigned → pending (provider cleared on sr at this point; recipient is customer)."""
    notify(
        recipient=sr.customer,
        notification_type=NotificationType.REQUEST_DECLINED,
        title="Provider Declined",
        body=f"The provider declined your request «{sr.title}». We'll find you another one.",
        data={"service_request_id": str(sr.id)},
    )


def notify_customer_cancelled_by_provider(sr):
    """any → cancelled (provider initiated)."""
    notify(
        recipient=sr.customer,
        notification_type=NotificationType.CANCELLED_BY_PROVIDER,
        title="Request Cancelled",
        body=f"Your request «{sr.title}» was cancelled by the provider.",
        data={"service_request_id": str(sr.id)},
    )


def notify_provider_quote_approved(sr):
    """quoted → confirmed."""
    notify(
        recipient=sr.provider,
        notification_type=NotificationType.QUOTE_APPROVED,
        title="Quote Approved",
        body=f"{sr.customer.get_full_name()} approved your quote of {sr.final_price} for «{sr.title}».",
        data={"service_request_id": str(sr.id)},
    )


def notify_provider_quote_rejected(sr, provider):
    """
    quoted → pending (sr.provider is None at this point — caller must pass the
    pre-transition provider snapshot captured before reject_quote() runs).
    """
    notify(
        recipient=provider,
        notification_type=NotificationType.QUOTE_REJECTED,
        title="Quote Rejected",
        body=f"{sr.customer.get_full_name()} rejected your quote for «{sr.title}».",
        data={"service_request_id": str(sr.id)},
    )


def notify_provider_cancelled_by_customer(sr, provider):
    """
    any → cancelled (customer initiated).

    Caller must pass the pre-transition provider snapshot because
    cancel() retains sr.provider in the DB but the caller's in-memory
    sr object may be stale after refresh. Explicit arg keeps the API
    symmetric with notify_provider_quote_rejected.
    """
    notify(
        recipient=provider,
        notification_type=NotificationType.CANCELLED_BY_CUSTOMER,
        title="Request Cancelled",
        body=f"{sr.customer.get_full_name()} cancelled the request «{sr.title}».",
        data={"service_request_id": str(sr.id)},
    )


def notify_provider_direct_request(sr):
    """pending → assigned via direct booking (customer personally chose this provider)."""
    notify(
        recipient=sr.provider,
        notification_type=NotificationType.DIRECT_BOOKING_REQUEST,
        title="Direct Booking Request",
        body=f"{sr.customer.get_full_name()} personally requested you for «{sr.title}».",
        data={"service_request_id": str(sr.id)},
    )


def notify_provider_payment_settled(sr):
    """in_progress → completed."""
    notify(
        recipient=sr.provider,
        notification_type=NotificationType.PAYMENT_SETTLED,
        title="Payment Settled",
        body=f"Payment of {sr.final_price} for «{sr.title}» has been settled. Check your earnings.",
        data={"service_request_id": str(sr.id)},
    )


# ── Onboarding notifications ───────────────────────────────────────────────────


def notify_provider_onboarding_approved(onboarding):
    """Staff approved the provider's onboarding application."""
    notify(
        recipient=onboarding.applicant,
        notification_type=NotificationType.ONBOARDING_APPROVED,
        title="Application Approved!",
        body=(
            f"Congratulations {onboarding.first_name}! Your provider account has been "
            "approved. You can now log in and start accepting jobs."
        ),
        data={"onboarding_id": str(onboarding.pk)},
    )


def notify_provider_onboarding_rejected(onboarding):
    """Staff rejected the provider's onboarding application."""
    resubmit_date = (
        onboarding.can_resubmit_after.strftime("%Y-%m-%d")
        if onboarding.can_resubmit_after
        else "30 days from now"
    )
    reason_snippet = (onboarding.rejection_reason or "No reason provided.")[:200]
    notify(
        recipient=onboarding.applicant,
        notification_type=NotificationType.ONBOARDING_REJECTED,
        title="Application Not Approved",
        body=(
            f"Unfortunately your application was not approved. Reason: {reason_snippet} "
            f"You may resubmit after {resubmit_date}."
        ),
        data={
            "onboarding_id": str(onboarding.pk),
            "rejection_reason": onboarding.rejection_reason,
            "can_resubmit_after": resubmit_date,
        },
    )


def notify_provider_onboarding_changes_required(onboarding):
    """Staff requested changes to the provider's onboarding application."""
    changes_snippet = (
        onboarding.change_requests or "Please check the app for details."
    )[:200]
    notify(
        recipient=onboarding.applicant,
        notification_type=NotificationType.ONBOARDING_CHANGES_REQUIRED,
        title="Changes Required",
        body=(
            f"Your application needs updates before it can be reviewed. "
            f"Required changes: {changes_snippet}"
        ),
        data={
            "onboarding_id": str(onboarding.pk),
            "change_requests": onboarding.change_requests,
        },
    )


def notify_provider_resubmit_available(provider):
    """30-day rejection cooldown has expired — provider can reapply."""
    notify(
        recipient=provider,
        notification_type=NotificationType.ONBOARDING_RESUBMIT_AVAILABLE,
        title="You Can Reapply Now",
        body=(
            "Your 30-day waiting period has ended. You can now resubmit your "
            "provider application from the app."
        ),
        data={},
    )
