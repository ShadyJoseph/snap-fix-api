"""
Notification system tests — inbox API, device registration, and Celery task.

FSM-event notification assertions live alongside the corresponding booking
view tests in apps/booking/tests/test_views.py.
"""

from unittest.mock import MagicMock, patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.notifications.choices import NotificationType
from apps.notifications.models import Notification
from factories import make_customer, make_provider

# ── Shared base ───────────────────────────────────────────────────────────────


class NotificationTestCase(APITestCase):
    def setUp(self):
        self.customer = make_customer()
        self.provider = make_provider()

    def _create_notification(self, recipient=None, is_read=False):
        return Notification.objects.create(
            recipient=recipient or self.customer,
            type=NotificationType.JOB_COMPLETED,
            title="Job Completed",
            body="Your job is done.",
            data={"service_request_id": "test-id"},
            is_read=is_read,
        )


# ── Notification inbox API ────────────────────────────────────────────────────


class NotificationInboxAPITest(NotificationTestCase):
    list_url = reverse("notifications:list")
    count_url = reverse("notifications:unread-count")
    read_all_url = reverse("notifications:read-all")

    def test_list_returns_own_notifications_only(self):
        self._create_notification(recipient=self.customer)
        self._create_notification(recipient=self.provider)
        self.client.force_authenticate(user=self.customer)

        response = self.client.get(self.list_url)
        results = response.data.get("results", response.data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(results), 1)

    def test_unread_filter(self):
        self._create_notification(is_read=False)
        self._create_notification(is_read=True)
        self.client.force_authenticate(user=self.customer)

        response = self.client.get(self.list_url + "?unread=true")
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["is_read"])

    def test_unread_count(self):
        self._create_notification(is_read=False)
        self._create_notification(is_read=False)
        self._create_notification(is_read=True)
        self.client.force_authenticate(user=self.customer)

        response = self.client.get(self.count_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["unread_count"], 2)

    def test_mark_single_as_read(self):
        notif = self._create_notification(is_read=False)
        self.client.force_authenticate(user=self.customer)

        url = reverse("notifications:mark-read", args=[notif.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_cannot_mark_other_users_notification_as_read(self):
        notif = self._create_notification(recipient=self.provider)
        self.client.force_authenticate(user=self.customer)

        url = reverse("notifications:mark-read", args=[notif.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_mark_all_as_read(self):
        self._create_notification(is_read=False)
        self._create_notification(is_read=False)
        self.client.force_authenticate(user=self.customer)

        response = self.client.post(self.read_all_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["marked_read"], 2)
        self.assertEqual(
            Notification.objects.filter(recipient=self.customer, is_read=False).count(),
            0,
        )

    def test_unauthenticated_request_rejected(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_notification_payload_shape(self):
        self._create_notification()
        self.client.force_authenticate(user=self.customer)

        response = self.client.get(self.list_url)
        results = response.data.get("results", response.data)
        item = results[0]
        for field in ("id", "type", "title", "body", "data", "is_read", "created_at"):
            self.assertIn(field, item, f"Missing field: {field}")


# ── Device registration API ───────────────────────────────────────────────────


VALID_TOKEN = "A" * 50  # minimum-length valid token (all alphanumeric)


class DeviceRegistrationAPITest(NotificationTestCase):
    register_url = reverse("notifications:device-register")

    def test_register_device_creates_fcm_record(self):
        from fcm_django.models import FCMDevice

        self.client.force_authenticate(user=self.customer)
        response = self.client.post(
            self.register_url,
            {"registration_id": VALID_TOKEN, "type": "android"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            FCMDevice.objects.filter(
                user=self.customer, registration_id=VALID_TOKEN
            ).exists()
        )

    def test_registering_same_token_twice_is_idempotent(self):
        from fcm_django.models import FCMDevice

        self.client.force_authenticate(user=self.customer)
        payload = {"registration_id": VALID_TOKEN, "type": "ios"}
        self.client.post(self.register_url, payload)
        response = self.client.post(self.register_url, payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            FCMDevice.objects.filter(registration_id=VALID_TOKEN).count(), 1
        )

    def test_token_too_short_returns_400(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.post(
            self.register_url,
            {"registration_id": "short", "type": "android"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("registration_id", response.data)

    def test_token_with_invalid_characters_returns_400(self):
        self.client.force_authenticate(user=self.customer)
        invalid_token = "A" * 49 + "!"  # 50 chars but has '!'
        response = self.client.post(
            self.register_url,
            {"registration_id": invalid_token, "type": "android"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("registration_id", response.data)

    def test_max_devices_per_user_enforced(self):
        from fcm_django.models import FCMDevice

        from apps.notifications.views import MAX_DEVICES_PER_USER

        self.client.force_authenticate(user=self.customer)
        # Register up to the cap.
        for i in range(MAX_DEVICES_PER_USER):
            token = f"{'A' * 49}{i}"
            FCMDevice.objects.create(
                user=self.customer,
                registration_id=token,
                type="android",
                active=True,
            )

        # Attempting to register a new distinct token should be blocked.
        new_token = "B" * 50
        response = self.client.post(
            self.register_url,
            {"registration_id": new_token, "type": "android"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Maximum", response.data["detail"])

    def test_re_registering_existing_token_skips_cap_check(self):
        """Updating an already-registered token must not be blocked by the cap."""
        from fcm_django.models import FCMDevice

        from apps.notifications.views import MAX_DEVICES_PER_USER

        self.client.force_authenticate(user=self.customer)
        existing_token = "C" * 50
        FCMDevice.objects.create(
            user=self.customer,
            registration_id=existing_token,
            type="android",
            active=True,
        )
        for i in range(MAX_DEVICES_PER_USER - 1):
            FCMDevice.objects.create(
                user=self.customer,
                registration_id=f"{'D' * 49}{i}",
                type="android",
                active=True,
            )

        # Re-registering the existing token should succeed even at the cap.
        response = self.client.post(
            self.register_url,
            {"registration_id": existing_token, "type": "ios"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unregister_device(self):
        from fcm_django.models import FCMDevice

        FCMDevice.objects.create(
            user=self.customer, registration_id=VALID_TOKEN, type="android", active=True
        )
        self.client.force_authenticate(user=self.customer)
        url = reverse("notifications:device-unregister", args=[VALID_TOKEN])
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(FCMDevice.objects.get(registration_id=VALID_TOKEN).active)

    def test_unregister_nonexistent_token_returns_404(self):
        self.client.force_authenticate(user=self.customer)
        url = reverse("notifications:device-unregister", args=["no-such-token"])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ── Celery task: send_push_notification ───────────────────────────────────────


class SendPushNotificationTaskTest(NotificationTestCase):
    """
    Unit tests for the send_push_notification Celery task.

    Firebase / FCM is fully mocked so these tests run without a real
    Firebase project or active broker.
    """

    TASK_PATH = "apps.notifications.tasks"

    def _run_task(self, user_id, title="Test", body="Body", data=None):
        from apps.notifications.tasks import send_push_notification

        return send_push_notification.apply(
            args=[str(user_id), title, body, data or {}]
        )

    @patch(f"{TASK_PATH}.FCMDevice")
    def test_returns_early_when_no_active_devices(self, mock_fcm):
        mock_fcm.objects.filter.return_value.exists.return_value = False

        result = self._run_task(self.customer.pk)

        self.assertTrue(result.successful())
        mock_fcm.objects.filter.return_value.send_message.assert_not_called()

    @patch(f"{TASK_PATH}.FCMDevice")
    @patch(f"{TASK_PATH}.Message")
    @patch(f"{TASK_PATH}.FCMNotification")
    def test_sends_message_to_all_active_devices(
        self, mock_notif_cls, mock_msg_cls, mock_fcm
    ):
        mock_devices = MagicMock()
        mock_devices.exists.return_value = True
        mock_fcm.objects.filter.return_value = mock_devices

        self._run_task(
            self.customer.pk,
            title="Hello",
            body="World",
            data={"service_request_id": "abc"},
        )

        mock_notif_cls.assert_called_once_with(title="Hello", body="World")
        mock_devices.send_message.assert_called_once()

    @patch(f"{TASK_PATH}.FCMDevice")
    @patch(f"{TASK_PATH}.Message")
    @patch(f"{TASK_PATH}.FCMNotification")
    def test_data_values_are_coerced_to_strings(
        self, mock_notif_cls, mock_msg_cls, mock_fcm
    ):
        mock_devices = MagicMock()
        mock_devices.exists.return_value = True
        mock_fcm.objects.filter.return_value = mock_devices

        self._run_task(self.customer.pk, data={"count": 42, "flag": True})

        _, call_kwargs = mock_msg_cls.call_args
        sent_data = call_kwargs.get("data") or mock_msg_cls.call_args[1].get("data", {})
        for v in sent_data.values():
            self.assertIsInstance(v, str)

    @patch(f"{TASK_PATH}.FCMDevice")
    def test_task_filters_by_correct_user_and_active_only(self, mock_fcm):
        mock_fcm.objects.filter.return_value.exists.return_value = False

        self._run_task(self.customer.pk)

        mock_fcm.objects.filter.assert_called_once_with(
            user_id=str(self.customer.pk), active=True
        )

    @patch(f"{TASK_PATH}.FCMDevice")
    def test_task_retries_on_fcm_failure(self, mock_fcm):
        from apps.notifications.tasks import send_push_notification

        mock_devices = MagicMock()
        mock_devices.exists.return_value = True
        mock_devices.send_message.side_effect = Exception("Firebase error")
        mock_fcm.objects.filter.return_value = mock_devices

        result = send_push_notification.apply(
            args=[str(self.customer.pk), "T", "B", {}],
            # apply() doesn't retry by default — override=False keeps it in-process
        )
        # Task should be marked as failed (retries exhausted in eager mode)
        self.assertTrue(result.failed())

    @patch(f"{TASK_PATH}.FCMDevice")
    def test_nonexistent_user_id_does_not_raise(self, mock_fcm):
        """A stale user ID (deleted user) returns early without crashing."""
        mock_fcm.objects.filter.return_value.exists.return_value = False

        result = self._run_task("00000000-0000-0000-0000-000000000000")
        self.assertTrue(result.successful())


# ── Celery task: purge_stale_fcm_devices ─────────────────────────────────────


class PurgeStaleDevicesTaskTest(NotificationTestCase):
    def test_deactivates_old_devices(self):
        from datetime import timedelta

        from django.utils import timezone
        from fcm_django.models import FCMDevice

        from apps.notifications.tasks import purge_stale_fcm_devices

        old_device = FCMDevice.objects.create(
            user=self.customer,
            registration_id=VALID_TOKEN,
            type="android",
            active=True,
        )
        # Backdate creation to beyond the 90-day threshold.
        FCMDevice.objects.filter(pk=old_device.pk).update(
            date_created=timezone.now() - timedelta(days=91)
        )

        purge_stale_fcm_devices.apply()

        old_device.refresh_from_db()
        self.assertFalse(old_device.active)

    def test_recent_devices_are_not_touched(self):
        from fcm_django.models import FCMDevice

        from apps.notifications.tasks import purge_stale_fcm_devices

        device = FCMDevice.objects.create(
            user=self.customer,
            registration_id=VALID_TOKEN,
            type="android",
            active=True,
        )

        purge_stale_fcm_devices.apply()

        device.refresh_from_db()
        self.assertTrue(device.active)


# ── Celery task: purge_old_notifications ─────────────────────────────────────


class PurgeOldNotificationsTaskTest(NotificationTestCase):
    def test_deletes_old_read_notifications(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.notifications.tasks import purge_old_notifications

        old = self._create_notification(is_read=True)
        Notification.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=91)
        )

        purge_old_notifications.apply()

        self.assertFalse(Notification.objects.filter(pk=old.pk).exists())

    def test_keeps_unread_notifications(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.notifications.tasks import purge_old_notifications

        unread = self._create_notification(is_read=False)
        Notification.objects.filter(pk=unread.pk).update(
            created_at=timezone.now() - timedelta(days=91)
        )

        purge_old_notifications.apply()

        self.assertTrue(Notification.objects.filter(pk=unread.pk).exists())

    def test_keeps_recent_read_notifications(self):
        from apps.notifications.tasks import purge_old_notifications

        recent = self._create_notification(is_read=True)

        purge_old_notifications.apply()

        self.assertTrue(Notification.objects.filter(pk=recent.pk).exists())
