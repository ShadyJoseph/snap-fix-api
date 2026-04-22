import uuid

from django.db import models

from .choices import NotificationType


class Notification(models.Model):
    """
    Persisted notification for the in-app inbox.

    Each record maps 1-to-1 with a push notification sent via FCM.
    The mobile app uses `type` to decide which screen to navigate to,
    and `data` to populate that screen (e.g. jump straight to the request).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    recipient = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=True,
    )
    type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
        db_index=True,
    )
    title = models.CharField(max_length=255)
    body = models.TextField()

    # Extra payload forwarded as-is to FCM data and returned by the API.
    # Always includes {"service_request_id": "<uuid>"} when applicable.
    data = models.JSONField(default=dict)

    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["recipient", "-created_at"], name="notif_recipient_created_idx"
            ),
            models.Index(
                fields=["recipient", "is_read"], name="notif_recipient_read_idx"
            ),
        ]

    def __str__(self):
        return f"[{self.type}] → {self.recipient_id}"
