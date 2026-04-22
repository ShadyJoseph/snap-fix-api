from django.urls import path

from .views import (
    MarkAllReadView,
    MarkReadView,
    NotificationListView,
    RegisterDeviceView,
    UnreadCountView,
    UnregisterDeviceView,
)

app_name = "notifications"

urlpatterns = [
    # ── Inbox ─────────────────────────────────────────────────────
    path("", NotificationListView.as_view(), name="list"),
    path("unread-count/", UnreadCountView.as_view(), name="unread-count"),
    path("read-all/", MarkAllReadView.as_view(), name="read-all"),
    path("<uuid:pk>/read/", MarkReadView.as_view(), name="mark-read"),
    # ── Device management ─────────────────────────────────────────
    path("devices/register/", RegisterDeviceView.as_view(), name="device-register"),
    path(
        "devices/<str:registration_id>/",
        UnregisterDeviceView.as_view(),
        name="device-unregister",
    ),
]
