import re

from django.db import IntegrityError, transaction
from django.http import Http404
from fcm_django.models import FCMDevice
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from .models import Notification
from .serializers import NotificationSerializer, RegisterDeviceSerializer

_FCM_TOKEN_RE = re.compile(r"^[A-Za-z0-9\-_:]+$")

MAX_DEVICES_PER_USER = 5


class DeviceRegistrationThrottle(UserRateThrottle):
    """Max 10 device registration attempts per hour per user."""

    scope = "device_registration"
    rate = "10/hour"


class NotificationListView(generics.ListAPIView):
    """
    GET /api/v1/notifications/
    Returns the authenticated user's notification inbox, newest first.
    Supports ?unread=true to show only unread.
    """

    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Notification.objects.filter(recipient=self.request.user)
        if self.request.query_params.get("unread") == "true":
            qs = qs.filter(is_read=False)
        return qs


class UnreadCountView(APIView):
    """
    GET /api/v1/notifications/unread-count/
    Returns { "unread_count": N }.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(
            recipient=request.user, is_read=False
        ).count()
        return Response({"unread_count": count})


class MarkReadView(APIView):
    """
    POST /api/v1/notifications/<id>/read/
    Marks a single notification as read.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            notification = Notification.objects.get(pk=pk, recipient=request.user)
        except Notification.DoesNotExist:
            raise Http404 from None
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=["is_read"])
        return Response(NotificationSerializer(notification).data)


class MarkAllReadView(APIView):
    """
    POST /api/v1/notifications/read-all/
    Marks all unread notifications as read.
    Returns { "marked_read": N }.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        updated = Notification.objects.filter(
            recipient=request.user, is_read=False
        ).update(is_read=True)
        return Response({"marked_read": updated})


class RegisterDeviceView(APIView):
    """
    POST /api/v1/notifications/devices/register/
    Register (or refresh) an FCM device token for the authenticated user.

    Body:
      { "registration_id": "<fcm_token>", "type": "android" | "ios" | "web" }

    Idempotent — re-posting the same token just updates it.
    Limited to MAX_DEVICES_PER_USER active devices per user.
    """

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [DeviceRegistrationThrottle]

    def post(self, request):
        serializer = RegisterDeviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["registration_id"]

        with transaction.atomic():
            # Lock this user's device rows so concurrent registrations serialise
            # through the cap check and don't race past it.
            user_devices = FCMDevice.objects.select_for_update().filter(
                user=request.user
            )
            already_registered = user_devices.filter(
                registration_id=token, active=True
            ).exists()

            if not already_registered:
                if user_devices.filter(active=True).count() >= MAX_DEVICES_PER_USER:
                    return Response(
                        {
                            "detail": f"Maximum {MAX_DEVICES_PER_USER} active devices allowed. "
                            "Unregister an existing device first."
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            # Delete then recreate so date_created reflects the latest registration.
            # This keeps the purge_stale_fcm_devices task accurate (it uses date_created).
            # Scoped to this user to avoid touching another user's token.
            user_devices.filter(registration_id=token).delete()
            try:
                FCMDevice.objects.create(
                    user=request.user,
                    registration_id=token,
                    type=serializer.validated_data["type"],
                    active=True,
                )
            except IntegrityError:
                # Another user already owns this token — refuse the reassignment.
                return Response(
                    {"detail": "Token is already registered to another account."},
                    status=status.HTTP_409_CONFLICT,
                )

        return Response(
            {"registered": True, "created": not already_registered},
            status=status.HTTP_201_CREATED
            if not already_registered
            else status.HTTP_200_OK,
        )


class UnregisterDeviceView(APIView):
    """
    DELETE /api/v1/notifications/devices/<registration_id>/
    Deactivate a device token (e.g. on logout).
    """

    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, registration_id):
        if len(registration_id) > 512 or not _FCM_TOKEN_RE.match(registration_id):
            raise ValidationError("Invalid FCM token format.")
        updated = FCMDevice.objects.filter(
            user=request.user, registration_id=registration_id
        ).update(active=False)
        if not updated:
            raise Http404
        return Response(status=status.HTTP_204_NO_CONTENT)
