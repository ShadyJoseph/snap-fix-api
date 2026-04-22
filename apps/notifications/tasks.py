import logging

from celery import shared_task
from fcm_django.models import FCMDevice
from firebase_admin.messaging import Message
from firebase_admin.messaging import Notification as FCMNotification

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def send_push_notification(self, user_id: str, title: str, body: str, data: dict):
    """
    Send an FCM push notification to all active devices of a user.

    Receives primitive arguments only (no ORM objects) so the task payload
    is fully JSON-serialisable and safe to retry without stale state.

    Retry schedule (3 retries = 4 total attempts): 60s → 120s → 240s.
    On the 4th failure Celery raises MaxRetriesExceededError and the task
    is moved to the dead-letter queue / logged as failed.
    """
    try:
        devices = FCMDevice.objects.filter(user_id=user_id, active=True)
        if not devices.exists():
            return

        # FCM data payload values must be strings.
        str_data = {k: str(v) for k, v in data.items()}

        devices.send_message(
            Message(
                notification=FCMNotification(title=title, body=body),
                data=str_data,
            )
        )
    except Exception as exc:
        logger.exception(
            "FCM push failed for user %s (attempt %s)",
            user_id,
            self.request.retries + 1,
        )
        raise self.retry(exc=exc, countdown=60 * 2**self.request.retries) from exc


@shared_task
def purge_stale_fcm_devices():
    """
    Deactivate FCM device records that have not been updated in 90+ days.
    Runs daily. FCM_DJANGO_SETTINGS DELETE_INACTIVE_DEVICES handles removal
    on send failure; this task handles devices that go silent without errors.
    """
    from datetime import timedelta

    from django.utils import timezone

    cutoff = timezone.now() - timedelta(days=90)
    updated = FCMDevice.objects.filter(active=True, date_updated__lt=cutoff).update(
        active=False
    )
    logger.info("purge_stale_fcm_devices: deactivated %d device(s)", updated)


@shared_task
def purge_old_notifications():
    """
    Delete read Notification rows older than 90 days.
    Runs weekly to keep the inbox table lean.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.notifications.models import Notification

    cutoff = timezone.now() - timedelta(days=90)
    deleted, _ = Notification.objects.filter(
        is_read=True, created_at__lt=cutoff
    ).delete()
    logger.info("purge_old_notifications: deleted %d notification(s)", deleted)
