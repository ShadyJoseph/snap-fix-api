import sys
import uuid
from unittest.mock import MagicMock, patch

from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.booking.choices import (
    CancelledBy,
    PaymentMethod,
    PaymentStatus,
    ServiceRequestStatus,
)
from apps.booking.models import ServiceRequest
from apps.notifications.choices import NotificationType
from apps.notifications.models import Notification
from factories import (
    make_category,
    make_completed_request,
    make_customer,
    make_image,
    make_provider,
    make_region,
    make_review,
    make_service_request,
)

TASK_PATH = "apps.notifications.tasks.send_push_notification.delay"

# ── Base ──────────────────────────────────────────────────────────────────────


class BookingTestCase(APITestCase):
    def setUp(self):
        self.customer = make_customer()
        self.provider = make_provider()
        self.category = make_category()
        self.region = make_region()
        # Provider must have the category to see/pick matching requests.
        self.provider.categories.add(self.category)

    def authenticate_customer(self):
        self.client.force_authenticate(user=self.customer)

    def authenticate_provider(self):
        self.client.force_authenticate(user=self.provider)

    def make_request(self, **kwargs):
        return make_service_request(self.customer, self.category, self.region, **kwargs)

    def assign_to_provider(self, sr, provider=None):
        provider = provider or self.provider
        sr.provider = provider
        sr.status = ServiceRequestStatus.ASSIGNED
        sr.save()
        return sr

    def set_status(self, sr, new_status, provider=None):
        sr.status = new_status
        if provider:
            sr.provider = provider
        sr.save()
        return sr

    def get_results(self, response):
        data = response.data
        return data.get("results", data) if isinstance(data, dict) else data


def make_stripe_mock(
    intent_id="pi_test123",
    client_secret="pi_test123_secret_xxx",  # noqa: S107
    capture_status="succeeded",
):
    """
    Return (stripe_module_mock, fake_stripe_error_class) for injection into sys.modules.

    Usage:
        stripe_mod, fake_stripe_error = make_stripe_mock()
        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            response = self.client.post(url, data)

    fake_stripe_error is a real Exception subclass so try/except stripe.error.StripeError
    works correctly inside the patched context.
    """

    class FakeStripeError(Exception):
        def __init__(self, message="Stripe error", user_message=None):
            super().__init__(message)
            self.user_message = user_message or message

    mock_intent = MagicMock()
    mock_intent.id = intent_id
    mock_intent.client_secret = client_secret
    mock_intent.status = capture_status

    stripe_mod = MagicMock()
    stripe_mod.PaymentIntent.create.return_value = mock_intent
    stripe_mod.PaymentIntent.capture.return_value = MagicMock(
        id=intent_id, status=capture_status
    )
    stripe_mod.error.StripeError = FakeStripeError
    return stripe_mod, FakeStripeError


# ── Unified: List + Create ────────────────────────────────────────────────────


class ServiceRequestListTests(BookingTestCase):
    url = reverse("bookings:request-list-create")

    def _valid_payload(self, **overrides):
        payload = {
            "category": self.category.id,
            "region": self.region.id,
            "address": "123 Test St",
            "floor_number": "3",
            "apartment_number": "12",
            "special_mark": "Blue door on the left",
            "latitude": 30.0444,
            "longitude": 31.2357,
            "title": "Fix leaking pipe",
            "description": "Pipe under sink is leaking",
            "preferred_date": "2026-06-01",
            "preferred_time": "10:00:00",
        }
        payload.update(overrides)
        return payload

    def _post_with_photo(self, **overrides):
        """POST a valid create payload including one photo."""
        return self.client.post(
            self.url, {**self._valid_payload(**overrides), "photos": make_image()}
        )

    # ── POST (customer only) ──────────────────────────────────

    def test_create_success_returns_pending(self):
        self.authenticate_customer()
        response = self._post_with_photo()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], ServiceRequestStatus.PENDING)
        self.assertIn("id", response.data)

    def test_create_assigns_customer_from_token(self):
        self.authenticate_customer()
        response = self._post_with_photo()
        sr = ServiceRequest.objects.get(id=response.data["id"])
        self.assertEqual(sr.customer, self.customer)

    def test_create_by_provider_returns_403(self):
        self.authenticate_provider()
        response = self.client.post(self.url, self._valid_payload())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_unauthenticated_returns_401(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_missing_required_fields_returns_400(self):
        self.authenticate_customer()
        response = self.client.post(self.url, {"title": "Incomplete"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ── GET — customer ────────────────────────────────────────

    def test_customer_list_returns_own_requests_only(self):
        self.authenticate_customer()
        other = make_customer(email="other@test.com")
        self.make_request()
        make_service_request(other, self.category, self.region)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(self.get_results(response)), 1)

    def test_customer_list_empty_when_no_requests(self):
        self.authenticate_customer()
        response = self.client.get(self.url)
        self.assertEqual(len(self.get_results(response)), 0)

    def test_customer_list_filter_by_status(self):
        self.authenticate_customer()
        self.make_request(title="Pending")
        completed = make_completed_request(
            self.customer, self.provider, self.category, self.region, title="Done"
        )
        response = self.client.get(self.url, {"status": ServiceRequestStatus.COMPLETED})
        results = self.get_results(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(str(results[0]["id"]), str(completed.id))

    def test_customer_list_review_null_before_rating(self):
        self.authenticate_customer()
        self.make_request()
        self.assertIsNone(self.get_results(self.client.get(self.url))[0]["review"])

    def test_customer_list_review_populated_after_rating(self):
        self.authenticate_customer()
        sr = make_completed_request(
            self.customer, self.provider, self.category, self.region
        )
        make_review(sr, self.customer, self.provider, rating=5)
        result = next(
            r
            for r in self.get_results(self.client.get(self.url))
            if str(r["id"]) == str(sr.id)
        )
        self.assertEqual(result["review"]["rating"], 5)

    # ── GET — provider ────────────────────────────────────────

    def test_provider_list_returns_own_jobs_only(self):
        self.authenticate_provider()
        assigned = self.assign_to_provider(self.make_request())
        self.make_request(title="Unassigned")  # no provider → should NOT appear
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [str(r["id"]) for r in self.get_results(response)]
        self.assertIn(str(assigned.id), ids)
        self.assertEqual(len(ids), 1)

    def test_provider_list_filter_by_status(self):
        self.authenticate_provider()
        self.set_status(
            self.make_request(title="Active"),
            ServiceRequestStatus.CONFIRMED,
            provider=self.provider,
        )
        completed = make_completed_request(
            self.customer, self.provider, self.category, self.region
        )
        response = self.client.get(self.url, {"status": ServiceRequestStatus.COMPLETED})
        results = self.get_results(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(str(results[0]["id"]), str(completed.id))

    def test_provider_list_review_populated_after_rating(self):
        self.authenticate_provider()
        sr = make_completed_request(
            self.customer, self.provider, self.category, self.region
        )
        make_review(sr, self.customer, self.provider, rating=3)
        result = next(
            r
            for r in self.get_results(self.client.get(self.url))
            if str(r["id"]) == str(sr.id)
        )
        self.assertEqual(result["review"]["rating"], 3)

    def test_list_unauthenticated_returns_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Customer: Detail ─────────────────────────────────────────────────────────


class CustomerRequestDetailTests(BookingTestCase):
    def test_get_own_request_success(self):
        self.authenticate_customer()
        sr = self.make_request()
        response = self.client.get(reverse("bookings:request-detail", args=[sr.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.data["id"]), str(sr.id))

    def test_get_other_customers_request_returns_404(self):
        other = make_customer(email="other@test.com")
        sr = make_service_request(other, self.category, self.region)
        self.authenticate_customer()
        response = self.client.get(reverse("bookings:request-detail", args=[sr.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_provider_gets_404_for_unassigned_request(self):
        # Pending request has no provider — provider queryset scopes to their jobs only
        sr = self.make_request()
        self.authenticate_provider()
        response = self.client.get(reverse("bookings:request-detail", args=[sr.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_provider_can_access_own_assigned_job(self):
        sr = self.assign_to_provider(self.make_request())
        self.authenticate_provider()
        response = self.client.get(reverse("bookings:request-detail", args=[sr.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.data["id"]), str(sr.id))

    def test_get_unauthenticated_returns_401(self):
        sr = self.make_request()
        response = self.client.get(reverse("bookings:request-detail", args=[sr.id]))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Customer: Cancel ─────────────────────────────────────────────────────────


class CustomerCancelTests(BookingTestCase):
    def _cancel_url(self, sr):
        return reverse("bookings:request-cancel", args=[sr.id])

    def test_cancel_pending_request(self):
        self.authenticate_customer()
        sr = self.make_request()
        response = self.client.post(self._cancel_url(sr), {"reason": "Changed my mind"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CANCELLED)
        self.assertEqual(sr.cancelled_by, CancelledBy.CUSTOMER)
        self.assertEqual(sr.cancellation_reason, "Changed my mind")

    def test_cancel_without_reason_is_allowed(self):
        self.authenticate_customer()
        sr = self.make_request()
        response = self.client.post(self._cancel_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CANCELLED)

    @patch(TASK_PATH)
    def test_cancel_assigned_request_notifies_provider(self, mock_push):
        self.authenticate_customer()
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(self._cancel_url(sr), {"reason": "Changed mind"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CANCELLED)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.provider, type=NotificationType.CANCELLED_BY_CUSTOMER
            ).exists()
        )
        mock_push.assert_called_once()

    def test_cannot_cancel_completed_request(self):
        self.authenticate_customer()
        sr = self.make_request()
        self.set_status(sr, ServiceRequestStatus.COMPLETED)
        response = self.client.post(self._cancel_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_cancel_already_cancelled_request(self):
        self.authenticate_customer()
        sr = self.make_request()
        self.set_status(sr, ServiceRequestStatus.CANCELLED)
        response = self.client.post(self._cancel_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_cancel_other_customers_request(self):
        other = make_customer(email="other@test.com")
        sr = make_service_request(other, self.category, self.region)
        self.authenticate_customer()
        response = self.client.post(self._cancel_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cancel_by_provider_returns_403(self):
        sr = self.make_request()
        self.authenticate_provider()
        response = self.client.post(self._cancel_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ── Provider: Incoming ────────────────────────────────────────────────────────


class ProviderIncomingTests(BookingTestCase):
    url = reverse("bookings:request-incoming")

    def test_returns_only_assigned_requests_for_this_provider(self):
        self.authenticate_provider()
        assigned = self.assign_to_provider(self.make_request())

        # same provider, different status — should NOT appear
        in_progress = self.make_request(title="In Progress Job")
        self.set_status(
            in_progress, ServiceRequestStatus.IN_PROGRESS, provider=self.provider
        )

        # different provider — should NOT appear
        other_provider = make_provider(email="other@provider.com")
        other_sr = self.assign_to_provider(
            self.make_request(title="Other Provider Job"), provider=other_provider
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self.get_results(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(str(results[0]["id"]), str(assigned.id))
        # ensure other_sr is referenced to avoid unused variable warning
        self.assertNotEqual(str(results[0]["id"]), str(other_sr.id))

    def test_customer_cannot_access_incoming(self):
        self.authenticate_customer()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_returns_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Provider: Accept ─────────────────────────────────────────────────────────


class ProviderAcceptTests(BookingTestCase):
    def _accept_url(self, sr):
        return reverse("bookings:request-accept", args=[sr.id])

    @patch(TASK_PATH)
    def test_accept_assigned_request_transitions_to_confirmed(self, mock_push):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(self._accept_url(sr))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CONFIRMED)
        self.assertIsNotNone(sr.confirmed_at)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.customer, type=NotificationType.REQUEST_ACCEPTED
            ).exists()
        )
        mock_push.assert_called_once()

    def test_cannot_accept_pending_request(self):
        self.authenticate_provider()
        sr = self.make_request()
        sr.provider = self.provider
        sr.save()
        response = self.client.post(self._accept_url(sr))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_accept_quoted_request_bypasses_customer_approval(self):
        """
        A provider must NOT be able to call /accept/ on a QUOTED request.
        Doing so would bypass the customer's price approval and set CONFIRMED
        with no final_price / final_price — the job would complete for free.
        """
        self.authenticate_provider()
        sr = self.make_request()
        sr.status = ServiceRequestStatus.QUOTED
        sr.provider = self.provider
        sr.quoted_price = "150.00"
        sr.save()
        response = self.client.post(self._accept_url(sr))
        # Endpoint filters by ASSIGNED — QUOTED request is invisible → 404
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.QUOTED)  # unchanged
        self.assertIsNone(sr.final_price)  # price was never locked

    def test_cannot_accept_other_providers_request(self):
        self.authenticate_provider()
        other_provider = make_provider(email="other@provider.com")
        sr = self.assign_to_provider(self.make_request(), provider=other_provider)
        response = self.client.post(self._accept_url(sr))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_customer_cannot_accept(self):
        sr = self.assign_to_provider(self.make_request())
        self.authenticate_customer()
        response = self.client.post(self._accept_url(sr))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ── Provider: Decline ─────────────────────────────────────────────────────────


class ProviderDeclineTests(BookingTestCase):
    def _decline_url(self, sr):
        return reverse("bookings:request-decline", args=[sr.id])

    @patch(TASK_PATH)
    def test_decline_returns_request_to_pending_and_clears_provider(self, mock_push):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(self._decline_url(sr), {"reason": "Not available"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.PENDING)
        self.assertIsNone(sr.provider)
        self.assertIsNone(sr.assigned_at)
        self.assertEqual(sr.decline_reason, "Not available")
        self.assertIsNotNone(sr.declined_at)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.customer, type=NotificationType.REQUEST_DECLINED
            ).exists()
        )
        mock_push.assert_called_once()

    def test_decline_without_reason_is_allowed(self):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(self._decline_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.PENDING)

    def test_cannot_decline_confirmed_request(self):
        self.authenticate_provider()
        sr = self.make_request()
        self.set_status(sr, ServiceRequestStatus.CONFIRMED, provider=self.provider)
        response = self.client.post(self._decline_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_decline_other_providers_request(self):
        self.authenticate_provider()
        other_provider = make_provider(email="other@provider.com")
        sr = self.assign_to_provider(self.make_request(), provider=other_provider)
        response = self.client.post(self._decline_url(sr))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ── Provider: Start ───────────────────────────────────────────────────────────


class ProviderStartTests(BookingTestCase):
    def _start_url(self, sr):
        return reverse("bookings:request-start", args=[sr.id])

    @patch(TASK_PATH)
    def test_start_confirmed_request_transitions_to_in_progress(self, mock_push):
        self.authenticate_provider()
        sr = self.make_request()
        self.set_status(sr, ServiceRequestStatus.CONFIRMED, provider=self.provider)
        response = self.client.post(self._start_url(sr))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.IN_PROGRESS)
        self.assertIsNotNone(sr.started_at)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.customer, type=NotificationType.JOB_STARTED
            ).exists()
        )
        mock_push.assert_called_once()

    def test_cannot_start_assigned_request(self):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(self._start_url(sr))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_start_pending_request(self):
        self.authenticate_provider()
        sr = self.make_request()
        sr.provider = self.provider
        sr.save()
        response = self.client.post(self._start_url(sr))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ── Provider: Complete ────────────────────────────────────────────────────────


class ProviderCompleteTests(BookingTestCase):
    def _complete_url(self, sr):
        return reverse("bookings:request-complete", args=[sr.id])

    def _in_progress_request(self, **kwargs):
        sr = self.make_request(**kwargs)
        self.set_status(sr, ServiceRequestStatus.IN_PROGRESS, provider=self.provider)
        return sr

    @patch(TASK_PATH)
    def test_complete_transitions_to_completed_and_marks_paid(self, mock_push):
        """Cash job (default): completes successfully, payment_status=paid immediately."""
        self.authenticate_provider()
        sr = self._in_progress_request()
        response = self.client.post(self._complete_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)
        self.assertEqual(sr.payment_status, PaymentStatus.PAID)
        self.assertIsNotNone(sr.completed_at)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.customer, type=NotificationType.JOB_COMPLETED
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.provider, type=NotificationType.PAYMENT_SETTLED
            ).exists()
        )
        self.assertEqual(mock_push.call_count, 2)

    def test_complete_without_final_price_is_allowed(self):
        """No final_price set (no quote step done): completes with amount=0, still PAID."""
        self.authenticate_provider()
        sr = self._in_progress_request()
        response = self.client.post(self._complete_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)
        self.assertEqual(sr.payment_status, PaymentStatus.PAID)

    def test_cannot_complete_confirmed_request(self):
        self.authenticate_provider()
        sr = self.make_request()
        self.set_status(sr, ServiceRequestStatus.CONFIRMED, provider=self.provider)
        response = self.client.post(self._complete_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_complete_assigned_request(self):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(self._complete_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ── Provider: Cancel ─────────────────────────────────────────────────────────


class ProviderCancelTests(BookingTestCase):
    def _cancel_url(self, sr):
        return reverse("bookings:request-provider-cancel", args=[sr.id])

    @patch(TASK_PATH)
    def test_cancel_assigned_request(self, mock_push):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(self._cancel_url(sr), {"reason": "Emergency"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CANCELLED)
        self.assertEqual(sr.cancelled_by, CancelledBy.PROVIDER)
        self.assertEqual(sr.cancellation_reason, "Emergency")
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.customer, type=NotificationType.CANCELLED_BY_PROVIDER
            ).exists()
        )
        mock_push.assert_called_once()

    def test_cancel_in_progress_request(self):
        self.authenticate_provider()
        sr = self.make_request()
        self.set_status(sr, ServiceRequestStatus.IN_PROGRESS, provider=self.provider)
        response = self.client.post(self._cancel_url(sr), {"reason": "Emergency"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CANCELLED)

    def test_cannot_cancel_completed_request(self):
        self.authenticate_provider()
        sr = self.make_request()
        self.set_status(sr, ServiceRequestStatus.COMPLETED, provider=self.provider)
        response = self.client.post(self._cancel_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_cancel_other_providers_request(self):
        self.authenticate_provider()
        other_provider = make_provider(email="other@provider.com")
        sr = self.assign_to_provider(self.make_request(), provider=other_provider)
        response = self.client.post(self._cancel_url(sr))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ── Provider: Open Pool ───────────────────────────────────────────────────────


class ProviderOpenRequestsTests(BookingTestCase):
    url = reverse("bookings:request-open-pool")

    def test_returns_only_pending_requests(self):
        self.authenticate_provider()
        pending = self.make_request(title="Pending Job")
        assigned = self.make_request(title="Assigned Job")
        self.assign_to_provider(assigned)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self.get_results(response)
        ids = [str(r["id"]) for r in results]
        self.assertIn(str(pending.id), ids)
        self.assertNotIn(str(assigned.id), ids)

    def test_urgent_requests_appear_first(self):
        self.authenticate_provider()
        normal = self.make_request(title="Normal", is_urgent=False)
        urgent = self.make_request(title="Urgent", is_urgent=True)

        response = self.client.get(self.url)
        results = self.get_results(response)
        ids = [str(r["id"]) for r in results]
        self.assertLess(ids.index(str(urgent.id)), ids.index(str(normal.id)))

    def test_customer_cannot_access_open_pool(self):
        self.authenticate_customer()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_returns_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_empty_pool_returns_empty_list(self):
        self.authenticate_provider()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(self.get_results(response)), 0)


# ── Provider: Pick (Self-Assign) ──────────────────────────────────────────────


class ProviderPickRequestTests(BookingTestCase):
    def _pick_url(self, sr):
        return reverse("bookings:request-pick", args=[sr.id])

    @patch(TASK_PATH)
    def test_pick_pending_request_transitions_to_assigned(self, mock_push):
        self.authenticate_provider()
        sr = self.make_request()
        response = self.client.post(self._pick_url(sr))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.ASSIGNED)
        self.assertEqual(sr.provider, self.provider)
        self.assertIsNotNone(sr.assigned_at)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.customer, type=NotificationType.REQUEST_ASSIGNED
            ).exists()
        )
        mock_push.assert_called_once()

    def test_pick_increments_provider_total_jobs(self):
        self.authenticate_provider()
        jobs_before = self.provider.total_jobs
        sr = self.make_request()
        self.client.post(self._pick_url(sr))
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.total_jobs, jobs_before + 1)

    def test_cannot_pick_if_already_has_assigned_job(self):
        self.authenticate_provider()
        self.assign_to_provider(self.make_request())  # active job
        second = self.make_request(title="Second Job")
        response = self.client.post(self._pick_url(second))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_pick_if_already_has_confirmed_job(self):
        self.authenticate_provider()
        confirmed = self.make_request(title="Confirmed Job")
        self.set_status(
            confirmed, ServiceRequestStatus.CONFIRMED, provider=self.provider
        )
        second = self.make_request(title="Second Job")
        response = self.client.post(self._pick_url(second))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_pick_if_already_has_in_progress_job(self):
        self.authenticate_provider()
        in_progress = self.make_request(title="In Progress Job")
        self.set_status(
            in_progress, ServiceRequestStatus.IN_PROGRESS, provider=self.provider
        )
        second = self.make_request(title="Second Job")
        response = self.client.post(self._pick_url(second))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_pick_if_already_has_quoted_job(self):
        """QUOTED status must also block picking a second job."""
        self.authenticate_provider()
        quoted = self.make_request(title="Quoted Job")
        self.set_status(quoted, ServiceRequestStatus.QUOTED, provider=self.provider)
        second = self.make_request(title="Second Job")
        response = self.client.post(self._pick_url(second))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_can_pick_after_previous_job_completed(self):
        """Completed jobs must not block picking a new one."""
        self.authenticate_provider()
        done = self.make_request(title="Done Job")
        self.set_status(done, ServiceRequestStatus.COMPLETED, provider=self.provider)
        new = self.make_request(title="New Job")
        response = self.client.post(self._pick_url(new))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cannot_pick_already_assigned_request(self):
        """A request grabbed by another provider is no longer pending."""
        self.authenticate_provider()
        other_provider = make_provider(email="other@provider.com")
        sr = self.assign_to_provider(self.make_request(), provider=other_provider)
        response = self.client.post(self._pick_url(sr))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_pick_nonexistent_request(self):
        self.authenticate_provider()
        response = self.client.post(
            reverse("bookings:request-pick", args=[uuid.uuid4()])
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_customer_cannot_pick(self):
        sr = self.make_request()
        self.authenticate_customer()
        response = self.client.post(self._pick_url(sr))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_returns_401(self):
        sr = self.make_request()
        response = self.client.post(self._pick_url(sr))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_two_providers_race_only_one_wins(self):
        """Both providers attempt to pick the same request — exactly one succeeds."""
        sr = self.make_request()
        second_provider = make_provider(email="second@provider.com")
        second_provider.categories.add(self.category)

        self.client.force_authenticate(user=self.provider)
        r1 = self.client.post(self._pick_url(sr))

        self.client.force_authenticate(user=second_provider)
        r2 = self.client.post(self._pick_url(sr))

        statuses = {r1.status_code, r2.status_code}
        self.assertIn(status.HTTP_200_OK, statuses)
        self.assertIn(status.HTTP_404_NOT_FOUND, statuses)

        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.ASSIGNED)
        self.assertIsNotNone(sr.provider)


# ── Regression: Full Lifecycle ────────────────────────────────────────────────


class FullLifecycleRegressionTest(BookingTestCase):
    """
    Walks a request through every valid state using the full new flow.
    Guards against regressions that break the happy path.

        pending → assigned → quoted → confirmed → in_progress → completed
    """

    def test_full_happy_path(self):
        # 1. Customer creates request (with photo — required)
        self.authenticate_customer()
        response = self.client.post(
            reverse("bookings:request-list-create"),
            {
                "category": self.category.id,
                "region": self.region.id,
                "address": "123 Test St",
                "floor_number": "3",
                "apartment_number": "12",
                "special_mark": "Blue door on the left",
                "latitude": 30.0444,
                "longitude": 31.2357,
                "title": "Full lifecycle test",
                "description": "Testing every step",
                "preferred_date": "2026-06-01",
                "preferred_time": "10:00:00",
                "photos": make_image(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        sr_id = response.data["id"]
        sr = ServiceRequest.objects.get(id=sr_id)
        self.assertEqual(sr.status, ServiceRequestStatus.PENDING)
        self.assertEqual(len(response.data["photos"]), 1)

        # 2. Admin assigns provider (direct model call)
        sr.assign(self.provider)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.ASSIGNED)
        self.assertEqual(sr.provider, self.provider)
        self.assertIsNotNone(sr.assigned_at)

        # 3. Provider quotes a price → QUOTED
        self.authenticate_provider()
        response = self.client.post(
            reverse("bookings:request-quote", args=[sr_id]), {"price": "200.00"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.QUOTED)
        self.assertEqual(str(sr.quoted_price), "200.00")

        # 4. Customer approves the quote → CONFIRMED, price locked
        self.authenticate_customer()
        response = self.client.post(
            reverse("bookings:request-approve-quote", args=[sr_id])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CONFIRMED)
        self.assertIsNotNone(sr.confirmed_at)
        self.assertEqual(str(sr.final_price), "200.00")
        self.assertEqual(str(sr.final_price), "200.00")

        # 5. Provider starts
        self.authenticate_provider()
        response = self.client.post(reverse("bookings:request-start", args=[sr_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.IN_PROGRESS)
        self.assertIsNotNone(sr.started_at)

        # 6. Provider completes — final_price locked, no body param needed
        response = self.client.post(
            reverse("bookings:request-complete", args=[sr_id]), {}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)
        self.assertEqual(str(sr.final_price), "200.00")  # locked from final_price
        self.assertEqual(sr.payment_status, PaymentStatus.PAID)  # cash default
        self.assertIsNotNone(sr.completed_at)

        # 7. Verify terminal — no further transitions allowed
        response = self.client.post(
            reverse("bookings:request-complete", args=[sr_id]), {}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.authenticate_customer()
        response = self.client.post(
            reverse("bookings:request-cancel", args=[sr_id]), {}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class DeclineAndReassignRegressionTest(BookingTestCase):
    """
    Provider declines → request returns to pending → can be reassigned.
    """

    def test_decline_then_reassign_and_complete(self):
        sr = self.make_request()

        # 1. Admin assigns first provider
        sr.assign(self.provider)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.ASSIGNED)

        # 2. First provider declines
        self.authenticate_provider()
        response = self.client.post(
            reverse("bookings:request-decline", args=[sr.id]), {"reason": "Unavailable"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.PENDING)
        self.assertIsNone(sr.provider)
        self.assertEqual(sr.decline_reason, "Unavailable")
        self.assertIsNotNone(sr.declined_at)

        # 3. Admin reassigns to second provider
        second_provider = make_provider(email="second@provider.com")
        sr.assign(second_provider)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.ASSIGNED)
        self.assertEqual(sr.provider, second_provider)

        # 4. Second provider uses admin override path (accept → start → complete)
        self.client.force_authenticate(user=second_provider)
        self.client.post(reverse("bookings:request-accept", args=[sr.id]))
        self.client.post(reverse("bookings:request-start", args=[sr.id]))
        response = self.client.post(
            reverse("bookings:request-complete", args=[sr.id]), {}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)
        self.assertEqual(sr.provider, second_provider)
        self.assertEqual(sr.payment_status, PaymentStatus.PAID)


class InvalidTransitionRegressionTest(BookingTestCase):
    """
    Verifies every illegal transition returns 400.
    Guards against accidentally loosening FSM guards.
    """

    def test_cannot_skip_steps_pending_to_complete(self):
        self.authenticate_provider()
        sr = self.make_request()
        sr.provider = self.provider
        sr.save()
        response = self.client.post(
            reverse("bookings:request-complete", args=[sr.id]), {}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_skip_steps_confirmed_to_complete(self):
        self.authenticate_provider()
        sr = self.make_request()
        self.set_status(sr, ServiceRequestStatus.CONFIRMED, provider=self.provider)
        response = self.client.post(
            reverse("bookings:request-complete", args=[sr.id]), {}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_start_without_confirming_first(self):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(reverse("bookings:request-start", args=[sr.id]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_accept_already_confirmed_request(self):
        self.authenticate_provider()
        sr = self.make_request()
        self.set_status(sr, ServiceRequestStatus.CONFIRMED, provider=self.provider)
        response = self.client.post(reverse("bookings:request-accept", args=[sr.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_cancel_completed_request(self):
        """COMPLETED is terminal — customer cannot cancel."""
        self.authenticate_customer()
        sr = self.make_request()
        self.set_status(sr, ServiceRequestStatus.COMPLETED)
        response = self.client.post(
            reverse("bookings:request-cancel", args=[sr.id]), {}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ProviderSelfAssignLifecycleTest(BookingTestCase):
    """
    Provider picks from the open pool and completes the full lifecycle.

        pending → (provider picks) → assigned → quoted → confirmed → in_progress → completed
    """

    def test_pick_then_full_lifecycle(self):
        # 1. Customer creates request (with photo)
        self.authenticate_customer()
        response = self.client.post(
            reverse("bookings:request-list-create"),
            {
                "category": self.category.id,
                "region": self.region.id,
                "address": "123 Test St",
                "floor_number": "3",
                "apartment_number": "12",
                "special_mark": "Blue door on the left",
                "latitude": 30.0444,
                "longitude": 31.2357,
                "title": "Self-assign lifecycle test",
                "description": "Provider picks from pool",
                "preferred_date": "2026-06-01",
                "preferred_time": "10:00:00",
                "photos": make_image(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        sr_id = response.data["id"]

        # 2. Provider sees it in the open pool
        self.authenticate_provider()
        pool_response = self.client.get(reverse("bookings:request-open-pool"))
        pool_ids = [r["id"] for r in self.get_results(pool_response)]
        self.assertIn(sr_id, pool_ids)

        # 3. Provider picks it
        response = self.client.post(reverse("bookings:request-pick", args=[sr_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], ServiceRequestStatus.ASSIGNED)

        # 4. Request no longer in open pool
        pool_response = self.client.get(reverse("bookings:request-open-pool"))
        pool_ids = [r["id"] for r in self.get_results(pool_response)]
        self.assertNotIn(sr_id, pool_ids)

        # 5. Appears in provider's incoming list
        incoming = self.client.get(reverse("bookings:request-incoming"))
        incoming_ids = [r["id"] for r in self.get_results(incoming)]
        self.assertIn(sr_id, incoming_ids)

        # 6. Provider uses admin-override accept → start → complete
        self.client.post(reverse("bookings:request-accept", args=[sr_id]))
        self.client.post(reverse("bookings:request-start", args=[sr_id]))
        response = self.client.post(
            reverse("bookings:request-complete", args=[sr_id]), {}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        sr = ServiceRequest.objects.get(id=sr_id)
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)
        self.assertEqual(sr.provider, self.provider)
        self.assertEqual(sr.payment_status, PaymentStatus.PAID)


# ── Rating ────────────────────────────────────────────────────────────────────


class CustomerRateProviderTests(BookingTestCase):
    def _rate_url(self, sr):
        return reverse("bookings:request-rate", args=[sr.id])

    def _completed_sr(self):
        return make_completed_request(
            self.customer, self.provider, self.category, self.region
        )

    def test_rate_completed_request_creates_review(self):
        self.authenticate_customer()
        sr = self._completed_sr()
        response = self.client.post(
            self._rate_url(sr), {"rating": 5, "comment": "Excellent!"}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["rating"], 5)
        self.assertEqual(response.data["comment"], "Excellent!")
        self.assertTrue(sr.review is not None or hasattr(sr, "review"))

    def test_rate_updates_provider_average_rating(self):
        self.authenticate_customer()
        sr = self._completed_sr()
        self.client.post(self._rate_url(sr), {"rating": 4})
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.total_reviews, 1)
        self.assertAlmostEqual(float(self.provider.average_rating), 4.0, places=1)

    def test_rating_without_comment_is_allowed(self):
        self.authenticate_customer()
        sr = self._completed_sr()
        response = self.client.post(self._rate_url(sr), {"rating": 3})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_idempotent_second_rate_returns_existing_review(self):
        self.authenticate_customer()
        sr = self._completed_sr()
        make_review(sr, self.customer, self.provider, rating=4)
        response = self.client.post(
            self._rate_url(sr), {"rating": 1, "comment": "Different"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["rating"], 4)

    def test_cannot_rate_non_completed_request(self):
        self.authenticate_customer()
        sr = self.make_request()  # pending
        response = self.client.post(self._rate_url(sr), {"rating": 5})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rating_below_1_returns_400(self):
        self.authenticate_customer()
        sr = self._completed_sr()
        response = self.client.post(self._rate_url(sr), {"rating": 0})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rating_above_5_returns_400(self):
        self.authenticate_customer()
        sr = self._completed_sr()
        response = self.client.post(self._rate_url(sr), {"rating": 6})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_provider_cannot_rate(self):
        self.authenticate_provider()
        sr = self._completed_sr()
        response = self.client.post(self._rate_url(sr), {"rating": 5})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_returns_401(self):
        sr = self._completed_sr()
        response = self.client.post(self._rate_url(sr), {"rating": 5})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_other_customers_request_returns_404(self):
        other = make_customer(email="other2@test.com")
        sr = make_completed_request(other, self.provider, self.category, self.region)
        self.authenticate_customer()
        response = self.client.post(self._rate_url(sr), {"rating": 5})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ── History Detail (unified) ──────────────────────────────────────────────────


class HistoryDetailTests(BookingTestCase):
    def _detail_url(self, sr):
        return reverse("bookings:history-detail", args=[sr.id])

    # ── Customer perspective ──────────────────────────────────────────────────

    def test_customer_gets_provider_card_and_review(self):
        self.authenticate_customer()
        sr = make_completed_request(
            self.customer, self.provider, self.category, self.region
        )
        response = self.client.get(self._detail_url(sr))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.data["id"]), str(sr.id))
        self.assertIn("provider", response.data)
        self.assertIn("review", response.data)
        self.assertIn("is_favorite_provider", response.data)

    def test_is_favorite_provider_false_by_default(self):
        self.authenticate_customer()
        sr = make_completed_request(
            self.customer, self.provider, self.category, self.region
        )
        response = self.client.get(self._detail_url(sr))
        self.assertFalse(response.data["is_favorite_provider"])

    def test_is_favorite_provider_true_when_favorited(self):
        self.authenticate_customer()
        sr = make_completed_request(
            self.customer, self.provider, self.category, self.region
        )
        self.customer.favorite_providers.add(self.provider)
        response = self.client.get(self._detail_url(sr))
        self.assertTrue(response.data["is_favorite_provider"])

    def test_customer_review_null_before_rating(self):
        self.authenticate_customer()
        sr = make_completed_request(
            self.customer, self.provider, self.category, self.region
        )
        response = self.client.get(self._detail_url(sr))
        self.assertIsNone(response.data["review"])

    def test_customer_review_populated_after_rating(self):
        self.authenticate_customer()
        sr = make_completed_request(
            self.customer, self.provider, self.category, self.region
        )
        make_review(sr, self.customer, self.provider, rating=4, comment="Solid")
        response = self.client.get(self._detail_url(sr))
        self.assertEqual(response.data["review"]["rating"], 4)
        self.assertEqual(response.data["review"]["comment"], "Solid")

    def test_customer_other_request_returns_404(self):
        other = make_customer(email="other4@test.com")
        sr = make_completed_request(other, self.provider, self.category, self.region)
        self.authenticate_customer()
        response = self.client.get(self._detail_url(sr))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ── Provider perspective ──────────────────────────────────────────────────

    def test_provider_gets_customer_card_and_review(self):
        self.authenticate_provider()
        sr = make_completed_request(
            self.customer, self.provider, self.category, self.region
        )
        response = self.client.get(self._detail_url(sr))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.data["id"]), str(sr.id))
        self.assertIn("customer", response.data)
        self.assertIn("review", response.data)

    def test_provider_review_null_when_not_rated(self):
        self.authenticate_provider()
        sr = make_completed_request(
            self.customer, self.provider, self.category, self.region
        )
        response = self.client.get(self._detail_url(sr))
        self.assertIsNone(response.data["review"])

    def test_provider_review_populated_after_customer_rates(self):
        self.authenticate_provider()
        sr = make_completed_request(
            self.customer, self.provider, self.category, self.region
        )
        make_review(sr, self.customer, self.provider, rating=2, comment="Meh")
        response = self.client.get(self._detail_url(sr))
        self.assertEqual(response.data["review"]["rating"], 2)

    def test_provider_other_job_returns_404(self):
        other_provider = make_provider(email="other6@provider.com")
        sr = make_completed_request(
            self.customer, other_provider, self.category, self.region
        )
        self.authenticate_provider()
        response = self.client.get(self._detail_url(sr))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ── Cross-role isolation ──────────────────────────────────────────────────

    def test_provider_token_on_customer_request_returns_404(self):
        sr = make_completed_request(
            self.customer, self.provider, self.category, self.region
        )
        other_provider = make_provider(email="cross@provider.com")
        self.client.force_authenticate(user=other_provider)
        response = self.client.get(self._detail_url(sr))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_returns_401(self):
        sr = make_completed_request(
            self.customer, self.provider, self.category, self.region
        )
        response = self.client.get(self._detail_url(sr))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ── New: Location Fields Required ────────────────────────────────────────────


class LocationFieldsTests(BookingTestCase):
    """Creating a request requires latitude, longitude, and all detail fields."""

    url = reverse("bookings:request-list-create")

    def _full_payload(self, **overrides):
        payload = {
            "category": self.category.id,
            "region": self.region.id,
            "address": "123 Test St",
            "floor_number": "3",
            "apartment_number": "12",
            "special_mark": "Blue door on the left",
            "latitude": 30.0444,
            "longitude": 31.2357,
            "title": "Fix leaking pipe",
            "description": "Pipe under sink is leaking",
            "preferred_date": "2026-06-01",
            "preferred_time": "10:00:00",
        }
        payload.update(overrides)
        return payload

    def _post(self, payload):
        self.authenticate_customer()
        return self.client.post(self.url, {**payload, "photos": make_image()})

    def test_missing_latitude_returns_400(self):
        payload = self._full_payload()
        del payload["latitude"]
        self.assertEqual(self._post(payload).status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_longitude_returns_400(self):
        payload = self._full_payload()
        del payload["longitude"]
        self.assertEqual(self._post(payload).status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_floor_number_returns_400(self):
        payload = self._full_payload()
        del payload["floor_number"]
        self.assertEqual(self._post(payload).status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_apartment_number_returns_400(self):
        payload = self._full_payload()
        del payload["apartment_number"]
        self.assertEqual(self._post(payload).status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_special_mark_returns_400(self):
        payload = self._full_payload()
        del payload["special_mark"]
        self.assertEqual(self._post(payload).status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_latitude_out_of_range_returns_400(self):
        self.assertEqual(
            self._post(self._full_payload(latitude=95.0)).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_invalid_longitude_out_of_range_returns_400(self):
        self.assertEqual(
            self._post(self._full_payload(longitude=200.0)).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_response_includes_all_location_fields(self):
        response = self._post(self._full_payload())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.data
        self.assertAlmostEqual(data["latitude"], 30.0444, places=3)
        self.assertAlmostEqual(data["longitude"], 31.2357, places=3)
        self.assertEqual(data["floor_number"], "3")
        self.assertEqual(data["apartment_number"], "12")
        self.assertEqual(data["special_mark"], "Blue door on the left")

    def test_location_persisted_as_point(self):
        response = self._post(self._full_payload())
        sr = ServiceRequest.objects.get(id=response.data["id"])
        self.assertIsNotNone(sr.location)
        self.assertAlmostEqual(sr.location.y, 30.0444, places=3)  # latitude
        self.assertAlmostEqual(sr.location.x, 31.2357, places=3)  # longitude


# ── New: Category Filtering ───────────────────────────────────────────────────


class CategoryFilteredOpenPoolTests(BookingTestCase):
    """Open pool only shows requests whose category matches the provider's categories."""

    url = reverse("bookings:request-open-pool")

    def setUp(self):
        super().setUp()
        self.other_category = make_category(name="Electrical", slug="electrical")

    def test_only_matching_category_requests_shown(self):
        self.authenticate_provider()
        matching = self.make_request(title="Plumbing Job")
        other_sr = make_service_request(
            self.customer, self.other_category, self.region, title="Electrical Job"
        )

        response = self.client.get(self.url)
        ids = [str(r["id"]) for r in self.get_results(response)]
        self.assertIn(str(matching.id), ids)
        self.assertNotIn(str(other_sr.id), ids)

    def test_provider_with_no_categories_sees_empty_pool(self):
        provider_no_cats = make_provider(email="nocats@provider.com")
        self.client.force_authenticate(user=provider_no_cats)
        self.make_request()
        response = self.client.get(self.url)
        self.assertEqual(len(self.get_results(response)), 0)

    def test_provider_with_multiple_categories_sees_all_matches(self):
        self.provider.categories.add(self.other_category)
        self.authenticate_provider()
        plumbing = self.make_request(title="Plumbing Job")
        electrical = make_service_request(
            self.customer, self.other_category, self.region, title="Electrical Job"
        )

        ids = [str(r["id"]) for r in self.get_results(self.client.get(self.url))]
        self.assertIn(str(plumbing.id), ids)
        self.assertIn(str(electrical.id), ids)


# ── New: Category Guard on Pick ───────────────────────────────────────────────


class CategoryGuardPickTests(BookingTestCase):
    """Provider cannot pick requests outside their registered categories."""

    def setUp(self):
        super().setUp()
        self.other_category = make_category(name="Electrical", slug="electrical")

    def test_pick_request_in_other_category_returns_404(self):
        """Direct URL manipulation must not bypass the category guard."""
        self.authenticate_provider()
        other_sr = make_service_request(self.customer, self.other_category, self.region)
        response = self.client.post(
            reverse("bookings:request-pick", args=[other_sr.id])
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_pick_request_in_own_category_succeeds(self):
        self.authenticate_provider()
        sr = self.make_request()
        response = self.client.post(reverse("bookings:request-pick", args=[sr.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ── New: Provider Location Update ────────────────────────────────────────────


class ProviderLocationUpdateTests(BookingTestCase):
    """PATCH /providers/me/location/ — lightweight location ping endpoint."""

    url = reverse("providers:provider-location")

    def test_update_location_returns_200_with_coords(self):
        self.authenticate_provider()
        response = self.client.patch(
            self.url, {"latitude": 30.0444, "longitude": 31.2357}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertAlmostEqual(response.data["latitude"], 30.0444, places=3)
        self.assertAlmostEqual(response.data["longitude"], 31.2357, places=3)

    def test_update_location_persists_point(self):
        self.authenticate_provider()
        self.client.patch(self.url, {"latitude": 29.9765, "longitude": 31.1313})
        self.provider.refresh_from_db()
        self.assertIsNotNone(self.provider.location)
        self.assertAlmostEqual(self.provider.location.y, 29.9765, places=3)
        self.assertAlmostEqual(self.provider.location.x, 31.1313, places=3)

    def test_repeated_updates_overwrite_previous_location(self):
        self.authenticate_provider()
        self.client.patch(self.url, {"latitude": 30.0, "longitude": 31.0})
        self.client.patch(self.url, {"latitude": 29.5, "longitude": 30.5})
        self.provider.refresh_from_db()
        self.assertAlmostEqual(self.provider.location.y, 29.5, places=1)

    def test_invalid_latitude_returns_400(self):
        self.authenticate_provider()
        response = self.client.patch(self.url, {"latitude": 95.0, "longitude": 31.0})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_longitude_returns_400(self):
        self.authenticate_provider()
        response = self.client.patch(self.url, {"latitude": 30.0, "longitude": 200.0})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_longitude_returns_400(self):
        self.authenticate_provider()
        response = self.client.patch(self.url, {"latitude": 30.0})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_latitude_returns_400(self):
        self.authenticate_provider()
        response = self.client.patch(self.url, {"longitude": 31.0})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_customer_cannot_use_this_endpoint(self):
        self.authenticate_customer()
        response = self.client.patch(self.url, {"latitude": 30.0, "longitude": 31.0})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_returns_401(self):
        response = self.client.patch(self.url, {"latitude": 30.0, "longitude": 31.0})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ── New: Distance & ETA Fields ────────────────────────────────────────────────


class DistanceAndETATests(BookingTestCase):
    """
    provider_distance_km / provider_eta_minutes appear in responses
    once the provider has a stored location.
    """

    def _set_provider_location(self, lat, lng):
        self.provider.location = Point(x=lng, y=lat, srid=4326)
        self.provider.save(update_fields=["location", "updated_at"])

    # ── No provider location ──────────────────────────────────

    def test_distance_null_when_provider_has_no_location(self):
        sr = self.assign_to_provider(self.make_request())
        self.authenticate_customer()
        data = self.client.get(reverse("bookings:request-detail", args=[sr.id])).data
        self.assertIsNone(data["provider_distance_km"])
        self.assertIsNone(data["provider_eta_minutes"])

    def test_distance_null_for_unassigned_request(self):
        sr = self.make_request()
        self.authenticate_customer()
        data = self.client.get(reverse("bookings:request-detail", args=[sr.id])).data
        self.assertIsNone(data["provider_distance_km"])
        self.assertIsNone(data["provider_eta_minutes"])

    # ── With provider location ────────────────────────────────

    def test_distance_present_when_provider_has_location(self):
        self._set_provider_location(30.0444, 31.2357)
        sr = self.assign_to_provider(self.make_request())
        self.authenticate_customer()
        data = self.client.get(reverse("bookings:request-detail", args=[sr.id])).data
        self.assertIsNotNone(data["provider_distance_km"])
        self.assertIsNotNone(data["provider_eta_minutes"])

    def test_eta_is_positive_integer(self):
        self._set_provider_location(30.314, 31.2357)
        sr = self.assign_to_provider(self.make_request())
        self.authenticate_customer()
        eta = self.client.get(reverse("bookings:request-detail", args=[sr.id])).data[
            "provider_eta_minutes"
        ]
        self.assertIsNotNone(eta)
        self.assertGreater(eta, 0)
        self.assertIsInstance(eta, int)

    def test_provider_sees_distance_to_job_in_history_detail(self):
        self._set_provider_location(30.0444, 31.2357)
        sr = make_completed_request(
            self.customer, self.provider, self.category, self.region
        )
        self.authenticate_provider()
        data = self.client.get(reverse("bookings:history-detail", args=[sr.id])).data
        self.assertIn("distance_to_job_km", data)
        self.assertIn("eta_to_job_minutes", data)
        self.assertIsNotNone(data["distance_to_job_km"])

    def test_open_pool_includes_distance_km_with_provider_location(self):
        self._set_provider_location(30.0444, 31.2357)
        self.make_request()
        self.authenticate_provider()
        results = self.get_results(
            self.client.get(reverse("bookings:request-open-pool"))
        )
        self.assertTrue(len(results) > 0)
        self.assertIn("distance_km", results[0])
        self.assertIsNotNone(results[0]["distance_km"])

    def test_open_pool_distance_km_null_without_provider_location(self):
        self.make_request()
        self.authenticate_provider()
        results = self.get_results(
            self.client.get(reverse("bookings:request-open-pool"))
        )
        self.assertTrue(len(results) > 0)
        self.assertIsNone(results[0]["distance_km"])


# ── Photos ────────────────────────────────────────────────────────────────────


class ServiceRequestPhotoTests(BookingTestCase):
    """Customer must upload ≥1 photo at booking time. Photos are visible to the provider."""

    url = reverse("bookings:request-list-create")

    def _base_payload(self, **overrides):
        payload = {
            "category": self.category.id,
            "region": self.region.id,
            "address": "123 Test St",
            "floor_number": "3",
            "apartment_number": "12",
            "special_mark": "Blue door on the left",
            "latitude": 30.0444,
            "longitude": 31.2357,
            "title": "Fix leaking pipe",
            "description": "Pipe under sink is leaking",
            "preferred_date": "2026-06-01",
            "preferred_time": "10:00:00",
        }
        payload.update(overrides)
        return payload

    def test_create_with_one_photo_succeeds(self):
        self.authenticate_customer()
        response = self.client.post(
            self.url, {**self._base_payload(), "photos": make_image()}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["photos"]), 1)

    def test_create_without_photos_returns_400(self):
        self.authenticate_customer()
        response = self.client.post(self.url, self._base_payload())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("photos", response.data)

    def test_create_with_more_than_5_photos_returns_400(self):
        self.authenticate_customer()
        photos = [make_image(f"photo_{i}.png") for i in range(6)]
        response = self.client.post(
            self.url, {**self._base_payload(), "photos": photos}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("photos", response.data)

    def test_photos_returned_in_response_with_correct_shape(self):
        self.authenticate_customer()
        response = self.client.post(
            self.url, {**self._base_payload(), "photos": make_image()}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        photos = response.data["photos"]
        self.assertEqual(len(photos), 1)
        self.assertIn("id", photos[0])
        self.assertIn("image", photos[0])
        self.assertIn("uploaded_at", photos[0])

    def test_provider_can_see_photos_on_assigned_request(self):
        """Photos must be visible to the provider so they can estimate the price."""
        sr = self.make_request()
        from apps.booking.models import ServiceRequestPhoto

        ServiceRequestPhoto.objects.create(
            service_request=sr,
            image=make_image(),
        )
        self.assign_to_provider(sr)

        self.authenticate_provider()
        response = self.client.get(reverse("bookings:request-detail", args=[sr.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["photos"]), 1)
        self.assertIn("image", response.data["photos"][0])

    def test_multiple_photos_all_returned(self):
        self.authenticate_customer()
        photos = [make_image(f"p{i}.png") for i in range(3)]
        response = self.client.post(
            self.url, {**self._base_payload(), "photos": photos}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["photos"]), 3)


# ── Provider: Quote ───────────────────────────────────────────────────────────


class ProviderQuoteViewTests(BookingTestCase):
    """Provider submits a price quote after picking an assigned request."""

    def _quote_url(self, sr):
        return reverse("bookings:request-quote", args=[sr.id])

    @patch(TASK_PATH)
    def test_quote_assigned_request_transitions_to_quoted(self, mock_push):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(self._quote_url(sr), {"price": "150.00"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.QUOTED)
        self.assertEqual(str(sr.quoted_price), "150.00")
        self.assertEqual(response.data["status"], ServiceRequestStatus.QUOTED)
        self.assertEqual(str(response.data["quoted_price"]), "150.00")
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.customer, type=NotificationType.QUOTE_RECEIVED
            ).exists()
        )
        mock_push.assert_called_once()

    def test_quote_wrong_provider_returns_404(self):
        """Provider cannot quote another provider's request."""
        self.authenticate_provider()
        other_provider = make_provider(email="other@provider.com")
        sr = self.assign_to_provider(self.make_request(), provider=other_provider)
        response = self.client.post(self._quote_url(sr), {"price": "100.00"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_quote_non_assigned_request_returns_404(self):
        """Provider can only quote requests in ASSIGNED status."""
        self.authenticate_provider()
        sr = self.make_request()
        sr.provider = self.provider
        sr.save()  # PENDING with provider set — not ASSIGNED
        response = self.client.post(self._quote_url(sr), {"price": "100.00"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_quote_negative_price_returns_400(self):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(self._quote_url(sr), {"price": "-10.00"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_quote_zero_price_is_allowed(self):
        """Zero price is a valid quote (free job)."""
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(self._quote_url(sr), {"price": "0.00"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.QUOTED)

    def test_customer_cannot_quote(self):
        sr = self.assign_to_provider(self.make_request())
        self.authenticate_customer()
        response = self.client.post(self._quote_url(sr), {"price": "100.00"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_returns_401(self):
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(self._quote_url(sr), {"price": "100.00"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Customer: Quote Approval ──────────────────────────────────────────────────


class CustomerQuoteApprovalTests(BookingTestCase):
    """Customer approves or rejects the provider's price quote."""

    def _approve_url(self, sr):
        return reverse("bookings:request-approve-quote", args=[sr.id])

    def _reject_url(self, sr):
        return reverse("bookings:request-reject-quote", args=[sr.id])

    def _quoted_request(self, quoted_price="150.00"):
        """SR in QUOTED state with a price set."""
        sr = self.make_request()
        sr.status = ServiceRequestStatus.QUOTED
        sr.provider = self.provider
        sr.quoted_price = quoted_price
        sr.save()
        return sr

    @patch(TASK_PATH)
    def test_approve_quote_confirms_and_locks_price(self, mock_push):
        self.authenticate_customer()
        sr = self._quoted_request(quoted_price="150.00")
        response = self.client.post(self._approve_url(sr))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CONFIRMED)
        self.assertIsNotNone(sr.confirmed_at)
        self.assertEqual(str(sr.final_price), "150.00")
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.provider, type=NotificationType.QUOTE_APPROVED
            ).exists()
        )
        mock_push.assert_called_once()

    @patch(TASK_PATH)
    def test_reject_quote_returns_to_pending_and_decrements_jobs(self, mock_push):
        self.authenticate_customer()
        self.provider.total_jobs = 1
        self.provider.save()
        sr = self._quoted_request()
        response = self.client.post(self._reject_url(sr))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.PENDING)
        self.assertIsNone(sr.provider_id)
        self.assertIsNone(sr.quoted_price)
        self.assertIsNone(sr.assigned_at)
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.total_jobs, 0)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.provider, type=NotificationType.QUOTE_REJECTED
            ).exists()
        )
        mock_push.assert_called_once()

    def test_rejected_request_reappears_in_open_pool(self):
        """After rejection, the request returns to the pool for another provider."""
        self.provider.total_jobs = 1
        self.provider.save()
        sr = self._quoted_request()
        self.authenticate_customer()
        self.client.post(self._reject_url(sr))
        self.authenticate_provider()
        response = self.client.get(reverse("bookings:request-open-pool"))
        ids = [str(r["id"]) for r in self.get_results(response)]
        self.assertIn(str(sr.id), ids)

    def test_reject_quote_wrong_customer_returns_404(self):
        other = make_customer(email="other@test.com")
        sr = self._quoted_request()
        self.client.force_authenticate(user=other)
        response = self.client.post(self._reject_url(sr))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_approve_non_quoted_request_returns_404(self):
        """Approve endpoint filters by status=QUOTED; non-QUOTED request is invisible."""
        self.authenticate_customer()
        sr = self.assign_to_provider(self.make_request())  # ASSIGNED, not QUOTED
        response = self.client.post(self._approve_url(sr))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_provider_cannot_approve_quote(self):
        sr = self._quoted_request()
        self.authenticate_provider()
        response = self.client.post(self._approve_url(sr))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_returns_401(self):
        sr = self._quoted_request()
        response = self.client.post(self._approve_url(sr))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # ── Payment split body params ─────────────────────────────

    def test_approve_quote_with_wallet_amount_updates_split(self):
        """wallet_amount sent in body is persisted and respected."""
        self.customer.wallet_balance = "200.00"
        self.customer.save()
        self.authenticate_customer()
        sr = self._quoted_request(quoted_price="100.00")
        response = self.client.post(
            self._approve_url(sr), {"wallet_amount": "60.00", "payment_method": "cash"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CONFIRMED)
        self.assertEqual(str(sr.wallet_amount), "60.00")
        self.assertEqual(sr.payment_method, PaymentMethod.CASH)

    def test_approve_quote_with_card_payment_method_stored(self):
        """payment_method=card accepted; no Stripe call at this stage."""
        self.authenticate_customer()
        sr = self._quoted_request(quoted_price="100.00")
        response = self.client.post(self._approve_url(sr), {"payment_method": "card"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CONFIRMED)
        self.assertEqual(sr.payment_method, PaymentMethod.CARD)

    def test_approve_quote_wallet_method_auto_fills_wallet_amount(self):
        """payment_method=wallet → wallet_amount automatically set to full quoted_price."""
        self.customer.wallet_balance = "200.00"
        self.customer.save()
        self.authenticate_customer()
        sr = self._quoted_request(quoted_price="100.00")
        response = self.client.post(self._approve_url(sr), {"payment_method": "wallet"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(str(sr.wallet_amount), "100.00")
        self.assertEqual(sr.payment_method, PaymentMethod.WALLET)

    def test_approve_quote_omitting_body_preserves_existing_split(self):
        """No body → wallet_amount and payment_method already on SR are kept."""
        self.customer.wallet_balance = "200.00"
        self.customer.save()
        self.authenticate_customer()
        sr = self._quoted_request(quoted_price="100.00")
        sr.wallet_amount = "50.00"
        sr.payment_method = PaymentMethod.CASH
        sr.save()
        response = self.client.post(self._approve_url(sr))  # no body
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(str(sr.wallet_amount), "50.00")
        self.assertEqual(sr.payment_method, PaymentMethod.CASH)

    def test_approve_quote_insufficient_wallet_returns_400(self):
        """wallet_amount exceeds customer wallet_balance → 400, status unchanged."""
        self.customer.wallet_balance = "30.00"
        self.customer.save()
        self.authenticate_customer()
        sr = self._quoted_request(quoted_price="100.00")
        response = self.client.post(
            self._approve_url(sr), {"wallet_amount": "60.00", "payment_method": "cash"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.QUOTED)  # not advanced


# ── Customer: Initiate Card Payment ──────────────────────────────────────────


class InitiateCardPaymentTests(BookingTestCase):
    """
    POST /bookings/requests/<id>/initiate-card-payment/

    Only valid when payment_method == CARD and card_amount > 0.
    Creates a Stripe PaymentIntent (manual capture) and stores its ID.
    """

    def _url(self, sr):
        return reverse("bookings:request-initiate-card-payment", args=[sr.id])

    RETURN_URL = "snapfix://payment/complete"

    def _confirmed_card_sr(self, final_price="100.00", wallet_amount="0.00"):
        """SR in CONFIRMED status with CARD payment method."""
        sr = self.make_request()
        sr.status = ServiceRequestStatus.CONFIRMED
        sr.provider = self.provider
        sr.final_price = final_price
        sr.wallet_amount = wallet_amount
        sr.payment_method = PaymentMethod.CARD
        sr.save()
        return sr

    def _payload(self, **kwargs):
        return {
            "stripe_payment_method_id": "pm_test",
            "return_url": self.RETURN_URL,
            **kwargs,
        }

    def test_happy_path_creates_intent_stores_id_returns_secret(self):
        """Creates PaymentIntent, stores stripe_payment_intent_id, returns client_secret."""
        stripe_mod, _ = make_stripe_mock(
            intent_id="pi_abc123",
            client_secret="pi_abc123_secret",  # noqa: S106
        )
        self.authenticate_customer()
        sr = self._confirmed_card_sr(final_price="100.00")

        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            response = self.client.post(self._url(sr), self._payload())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["stripe_client_secret"], "pi_abc123_secret")
        sr.refresh_from_db()
        self.assertEqual(sr.stripe_payment_intent_id, "pi_abc123")

        create_call = stripe_mod.PaymentIntent.create.call_args
        self.assertEqual(create_call.kwargs["amount"], 10000)  # 100.00 * 100
        self.assertEqual(create_call.kwargs["capture_method"], "manual")
        self.assertEqual(create_call.kwargs["confirm"], True)
        self.assertEqual(create_call.kwargs["return_url"], self.RETURN_URL)

    def test_partial_wallet_card_amount_sent_to_stripe(self):
        """Stripe is charged only the card_amount (final_price - wallet_amount)."""
        stripe_mod, _ = make_stripe_mock()
        self.authenticate_customer()
        sr = self._confirmed_card_sr(final_price="100.00", wallet_amount="40.00")

        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            response = self.client.post(self._url(sr), self._payload())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        create_call = stripe_mod.PaymentIntent.create.call_args
        self.assertEqual(create_call.kwargs["amount"], 6000)  # 60.00 * 100

    def test_wrong_payment_method_not_card_returns_400(self):
        """payment_method=cash → 400; only CARD needs this step."""
        self.authenticate_customer()
        sr = self._confirmed_card_sr()
        sr.payment_method = PaymentMethod.CASH
        sr.save()
        response = self.client.post(self._url(sr), self._payload())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_wallet_covers_full_price_returns_400(self):
        """wallet_amount == final_price → card_amount == 0 → 400."""
        self.authenticate_customer()
        sr = self._confirmed_card_sr(final_price="100.00", wallet_amount="100.00")
        response = self.client.post(self._url(sr), self._payload())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_wrong_status_pending_returns_404(self):
        """Status must be CONFIRMED or IN_PROGRESS; PENDING returns 404."""
        self.authenticate_customer()
        sr = self.make_request()
        sr.payment_method = PaymentMethod.CARD
        sr.final_price = "100.00"
        sr.save()  # PENDING
        response = self.client.post(self._url(sr), self._payload())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_in_progress_status_accepted(self):
        """IN_PROGRESS is also a valid status for this endpoint."""
        stripe_mod, _ = make_stripe_mock()
        self.authenticate_customer()
        sr = self._confirmed_card_sr()
        sr.status = ServiceRequestStatus.IN_PROGRESS
        sr.save()

        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            response = self.client.post(self._url(sr), self._payload())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_stripe_error_returns_400_with_message(self):
        """Stripe raises StripeError → 400 with the error message."""
        stripe_mod, fake_stripe_error = make_stripe_mock()  # N806
        stripe_mod.PaymentIntent.create.side_effect = fake_stripe_error(
            user_message="Your card was declined."
        )
        self.authenticate_customer()
        sr = self._confirmed_card_sr()

        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            response = self.client.post(self._url(sr), self._payload())

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Stripe error", str(response.data))

    def test_missing_stripe_payment_method_id_returns_400(self):
        """Serializer requires stripe_payment_method_id → 400 when omitted."""
        stripe_mod, _ = make_stripe_mock()
        self.authenticate_customer()
        sr = self._confirmed_card_sr()

        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            response = self.client.post(self._url(sr), {"return_url": self.RETURN_URL})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        stripe_mod.PaymentIntent.create.assert_not_called()

    def test_missing_return_url_returns_400(self):
        """Serializer requires return_url → 400 when omitted; Stripe never called."""
        stripe_mod, _ = make_stripe_mock()
        self.authenticate_customer()
        sr = self._confirmed_card_sr()

        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            response = self.client.post(
                self._url(sr), {"stripe_payment_method_id": "pm_test"}
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        stripe_mod.PaymentIntent.create.assert_not_called()

    def test_wrong_customer_returns_404(self):
        """Other customer cannot access this request."""
        other = make_customer(email="other@test.com")
        sr = self._confirmed_card_sr()
        self.client.force_authenticate(user=other)
        response = self.client.post(self._url(sr), self._payload())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_provider_cannot_initiate_returns_403(self):
        sr = self._confirmed_card_sr()
        self.authenticate_provider()
        response = self.client.post(self._url(sr), self._payload())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_returns_401(self):
        sr = self._confirmed_card_sr()
        response = self.client.post(self._url(sr), self._payload())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Provider: Complete + Payment ──────────────────────────────────────────────


class ProviderCompletePaymentTests(BookingTestCase):
    """
    Payment rules at completion:
      CASH   → payment_status=PAID immediately (honor system). No available_balance credit.
      WALLET → deduct customer wallet (select_for_update).
               Sufficient  → PAID, credit available_balance.
               Insufficient → PENDING, do NOT credit available_balance.
    """

    def _complete_url(self, sr):
        return reverse("bookings:request-complete", args=[sr.id])

    def _in_progress_with_price(self, final_price="100.00", **kwargs):
        """SR in IN_PROGRESS with final_price set."""
        sr = self.make_request(**kwargs)
        sr.final_price = final_price
        if sr.payment_method == PaymentMethod.WALLET and not getattr(
            sr, "wallet_amount", None
        ):
            sr.wallet_amount = final_price
        sr.status = ServiceRequestStatus.IN_PROGRESS
        sr.provider = self.provider
        sr.save()
        return sr

    def test_cash_complete_marks_paid_no_available_balance_credit(self):
        """Cash: PAID immediately. Platform never received money → no available_balance."""
        self.authenticate_provider()
        self.provider.available_balance = "0.00"
        self.provider.total_earnings = "0.00"
        self.provider.save()
        sr = self._in_progress_with_price(final_price="100.00")  # default cash

        response = self.client.post(self._complete_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)
        self.assertEqual(sr.payment_status, PaymentStatus.PAID)
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.completed_jobs, 1)
        self.assertEqual(str(self.provider.total_earnings), "100.00")
        self.assertEqual(str(self.provider.available_balance), "0.00")  # untouched

    def test_wallet_sufficient_marks_paid_and_credits_both(self):
        """Wallet, sufficient balance: PAID, customer debited, provider available_balance credited."""
        self.authenticate_provider()
        self.customer.wallet_balance = "200.00"
        self.customer.save()
        self.provider.available_balance = "0.00"
        self.provider.total_earnings = "0.00"
        self.provider.save()
        sr = self._in_progress_with_price(
            final_price="100.00", payment_method=PaymentMethod.WALLET
        )

        response = self.client.post(self._complete_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.payment_status, PaymentStatus.PAID)
        self.customer.refresh_from_db()
        self.assertEqual(str(self.customer.wallet_balance), "100.00")  # debited
        self.provider.refresh_from_db()
        self.assertEqual(str(self.provider.total_earnings), "100.00")
        self.assertEqual(str(self.provider.available_balance), "100.00")  # credited

    def test_wallet_insufficient_returns_400(self):
        """Wallet, insufficient balance: raises 400."""
        self.authenticate_provider()
        self.customer.wallet_balance = "50.00"
        self.customer.save()
        self.provider.available_balance = "0.00"
        self.provider.total_earnings = "0.00"
        self.provider.save()
        sr = self._in_progress_with_price(
            final_price="100.00", payment_method=PaymentMethod.WALLET
        )

        response = self.client.post(self._complete_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.IN_PROGRESS)

    def test_complete_uses_final_price_body_param_ignored(self):
        """Body params are ignored — complete() uses final_price set at quote approval."""
        self.authenticate_provider()
        sr = self._in_progress_with_price(final_price="150.00")
        response = self.client.post(self._complete_url(sr), {"final_price": "999.00"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(str(sr.final_price), "150.00")  # locked, not 999

    def test_complete_without_final_price_uses_zero(self):
        """No quote step done → final_price=None → amount=0 → PAID with zero."""
        self.authenticate_provider()
        sr = self.make_request()
        sr.status = ServiceRequestStatus.IN_PROGRESS
        sr.provider = self.provider
        sr.save()  # final_price=None

        response = self.client.post(self._complete_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)
        self.assertEqual(sr.payment_status, PaymentStatus.PAID)

    # ── CARD payment tests ────────────────────────────────────

    def test_card_complete_captures_stripe_marks_paid_credits_provider(self):
        """
        CARD: Stripe PaymentIntent captured, payment_status=PAID,
        provider available_balance credited for the full card amount.
        """
        stripe_mod, _ = make_stripe_mock(
            intent_id="pi_card_test", capture_status="succeeded"
        )
        self.authenticate_provider()
        self.provider.available_balance = "0.00"
        self.provider.total_earnings = "0.00"
        self.provider.save()
        sr = self._in_progress_with_price(
            final_price="100.00", payment_method=PaymentMethod.CARD
        )
        sr.stripe_payment_intent_id = "pi_card_test"
        sr.save()

        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            response = self.client.post(self._complete_url(sr))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)
        self.assertEqual(sr.payment_status, PaymentStatus.PAID)
        stripe_mod.PaymentIntent.capture.assert_called_once_with("pi_card_test")
        self.provider.refresh_from_db()
        self.assertEqual(str(self.provider.total_earnings), "100.00")
        self.assertEqual(str(self.provider.available_balance), "100.00")

    def test_card_complete_missing_intent_id_returns_400_and_rolls_back(self):
        """
        CARD with no stripe_payment_intent_id → 400.
        Customer must call /initiate-card-payment/ first.
        SR stays IN_PROGRESS; Stripe is never contacted.
        """
        stripe_mod, _ = make_stripe_mock()
        self.authenticate_provider()
        sr = self._in_progress_with_price(
            final_price="100.00", payment_method=PaymentMethod.CARD
        )
        # stripe_payment_intent_id defaults to ""

        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            response = self.client.post(self._complete_url(sr))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.IN_PROGRESS)  # rolled back
        stripe_mod.PaymentIntent.capture.assert_not_called()

    def test_card_complete_stripe_capture_fails_returns_400_and_rolls_back(self):
        """
        Stripe capture raises StripeError → 400, SR stays IN_PROGRESS.
        The @transaction.atomic on complete() rolls back any partial wallet deduction.
        """
        stripe_mod, fake_stripe_error = make_stripe_mock()  # N806 fix
        stripe_mod.PaymentIntent.capture.side_effect = fake_stripe_error(
            user_message="Insufficient funds"
        )
        self.authenticate_provider()
        sr = self._in_progress_with_price(
            final_price="100.00", payment_method=PaymentMethod.CARD
        )
        sr.stripe_payment_intent_id = "pi_will_fail"
        sr.save()

        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            response = self.client.post(self._complete_url(sr))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.IN_PROGRESS)

    def test_card_partial_wallet_deducts_wallet_and_captures_card_remainder(self):
        """
        Hybrid split: wallet_amount=40, card_amount=60, final_price=100.
        Wallet is deducted from customer, card remainder captured via Stripe.
        Provider available_balance credited for both portions.
        """
        stripe_mod, _ = make_stripe_mock(intent_id="pi_hybrid")
        self.authenticate_provider()
        self.customer.wallet_balance = "100.00"
        self.customer.save()
        self.provider.available_balance = "0.00"
        self.provider.total_earnings = "0.00"
        self.provider.save()

        sr = self._in_progress_with_price(
            final_price="100.00", payment_method=PaymentMethod.CARD
        )
        sr.wallet_amount = "40.00"
        sr.stripe_payment_intent_id = "pi_hybrid"
        sr.save()

        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            response = self.client.post(self._complete_url(sr))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.payment_status, PaymentStatus.PAID)

        self.customer.refresh_from_db()
        self.assertEqual(str(self.customer.wallet_balance), "60.00")  # 100 - 40

        stripe_mod.PaymentIntent.capture.assert_called_once_with("pi_hybrid")

        self.provider.refresh_from_db()
        self.assertEqual(str(self.provider.total_earnings), "100.00")
        self.assertEqual(str(self.provider.available_balance), "100.00")

    def test_card_wallet_only_split_skips_stripe_capture(self):
        """
        payment_method=CARD but wallet covers 100% → card_amount=0
        → _capture_stripe_payment is not reached, no Stripe call.
        """
        stripe_mod, _ = make_stripe_mock()
        self.authenticate_provider()
        self.customer.wallet_balance = "200.00"
        self.customer.save()

        sr = self._in_progress_with_price(
            final_price="100.00", payment_method=PaymentMethod.CARD
        )
        sr.wallet_amount = "100.00"  # covers everything
        sr.stripe_payment_intent_id = "pi_not_needed"
        sr.save()

        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            response = self.client.post(self._complete_url(sr))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.payment_status, PaymentStatus.PAID)
        stripe_mod.PaymentIntent.capture.assert_not_called()

    def test_card_stripe_failure_rolls_back_wallet_deduction(self):
        """
        Hybrid split: wallet deducted first, then Stripe fails.
        The @transaction.atomic on complete() must roll back the wallet deduction.
        """
        stripe_mod, fake_stripe_error = make_stripe_mock()  # N806 fix
        stripe_mod.PaymentIntent.capture.side_effect = fake_stripe_error(
            user_message="Card declined"
        )
        self.authenticate_provider()
        self.customer.wallet_balance = "100.00"
        self.customer.save()

        sr = self._in_progress_with_price(
            final_price="100.00", payment_method=PaymentMethod.CARD
        )
        sr.wallet_amount = "40.00"
        sr.stripe_payment_intent_id = "pi_will_fail"
        sr.save()

        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            response = self.client.post(self._complete_url(sr))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.customer.refresh_from_db()
        self.assertEqual(str(self.customer.wallet_balance), "100.00")
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.IN_PROGRESS)


# ── Notification content assertions ───────────────────────────────────────────


class NotificationContentTest(BookingTestCase):
    """
    Asserts the title, body, and data payload of every FSM-triggered notification.
    Complements the type/recipient checks in individual view tests.
    """

    def _get_notification(self, recipient, notification_type):
        return Notification.objects.get(recipient=recipient, type=notification_type)

    # ── Provider picks request (pending → assigned) ────────────

    @patch(TASK_PATH)
    def test_request_assigned_notification_content(self, _mock_push):
        self.authenticate_provider()
        sr = self.make_request(title="Leaking Pipe")
        self.client.post(reverse("bookings:request-pick", args=[sr.id]))
        sr.refresh_from_db()

        notif = self._get_notification(self.customer, NotificationType.REQUEST_ASSIGNED)
        self.assertEqual(notif.title, "Provider Assigned")
        self.assertIn(sr.provider.get_full_name(), notif.body)
        self.assertIn("Leaking Pipe", notif.body)
        self.assertEqual(notif.data["service_request_id"], str(sr.id))

    # ── Provider submits quote (assigned → quoted) ─────────────

    @patch(TASK_PATH)
    def test_quote_received_notification_content(self, _mock_push):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request(title="AC Repair"))
        self.client.post(
            reverse("bookings:request-quote", args=[sr.id]), {"price": "250.00"}
        )
        sr.refresh_from_db()

        notif = self._get_notification(self.customer, NotificationType.QUOTE_RECEIVED)
        self.assertEqual(notif.title, "New Quote")
        self.assertIn("250", notif.body)
        self.assertIn("AC Repair", notif.body)
        self.assertEqual(notif.data["service_request_id"], str(sr.id))

    # ── Provider accepts directly (assigned → confirmed) ───────

    @patch(TASK_PATH)
    def test_request_accepted_notification_content(self, _mock_push):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request(title="Painting"))
        self.client.post(reverse("bookings:request-accept", args=[sr.id]))
        sr.refresh_from_db()

        notif = self._get_notification(self.customer, NotificationType.REQUEST_ACCEPTED)
        self.assertEqual(notif.title, "Request Accepted")
        self.assertIn(self.provider.get_full_name(), notif.body)
        self.assertIn("Painting", notif.body)
        self.assertEqual(notif.data["service_request_id"], str(sr.id))

    # ── Customer approves quote (quoted → confirmed) ───────────

    @patch(TASK_PATH)
    def test_quote_approved_notification_content(self, _mock_push):
        self.authenticate_customer()
        sr = self.make_request(title="Plumbing")
        sr.status = ServiceRequestStatus.QUOTED
        sr.provider = self.provider
        sr.quoted_price = "180.00"
        sr.save()
        self.client.post(reverse("bookings:request-approve-quote", args=[sr.id]))
        sr.refresh_from_db()

        notif = self._get_notification(self.provider, NotificationType.QUOTE_APPROVED)
        self.assertEqual(notif.title, "Quote Approved")
        self.assertIn(self.customer.get_full_name(), notif.body)
        self.assertIn("180", notif.body)
        self.assertIn("Plumbing", notif.body)
        self.assertEqual(notif.data["service_request_id"], str(sr.id))

    # ── Customer rejects quote (quoted → pending) ──────────────

    @patch(TASK_PATH)
    def test_quote_rejected_notification_content(self, _mock_push):
        self.authenticate_customer()
        sr = self.make_request(title="Tiling")
        sr.status = ServiceRequestStatus.QUOTED
        sr.provider = self.provider
        sr.quoted_price = "300.00"
        self.provider.total_jobs = 1
        self.provider.save()
        sr.save()
        self.client.post(reverse("bookings:request-reject-quote", args=[sr.id]))

        notif = self._get_notification(self.provider, NotificationType.QUOTE_REJECTED)
        self.assertEqual(notif.title, "Quote Rejected")
        self.assertIn(self.customer.get_full_name(), notif.body)
        self.assertIn("Tiling", notif.body)
        self.assertEqual(notif.data["service_request_id"], str(sr.id))

    # ── Provider declines assignment (assigned → pending) ──────

    @patch(TASK_PATH)
    def test_request_declined_notification_content(self, _mock_push):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request(title="Carpentry"))
        self.client.post(
            reverse("bookings:request-decline", args=[sr.id]), {"reason": "Busy"}
        )

        notif = self._get_notification(self.customer, NotificationType.REQUEST_DECLINED)
        self.assertEqual(notif.title, "Provider Declined")
        self.assertIn("Carpentry", notif.body)
        self.assertEqual(notif.data["service_request_id"], str(sr.id))

    # ── Provider starts job (confirmed → in_progress) ──────────

    @patch(TASK_PATH)
    def test_job_started_notification_content(self, _mock_push):
        self.authenticate_provider()
        sr = self.make_request(title="Electrical Fix")
        self.set_status(sr, ServiceRequestStatus.CONFIRMED, provider=self.provider)
        self.client.post(reverse("bookings:request-start", args=[sr.id]))
        sr.refresh_from_db()

        notif = self._get_notification(self.customer, NotificationType.JOB_STARTED)
        self.assertEqual(notif.title, "Job Started")
        self.assertIn(self.provider.get_full_name(), notif.body)
        self.assertIn("Electrical Fix", notif.body)
        self.assertEqual(notif.data["service_request_id"], str(sr.id))

    # ── Provider completes job (in_progress → completed) ───────

    @patch(TASK_PATH)
    def test_job_completed_and_payment_settled_notification_content(self, _mock_push):
        self.authenticate_provider()
        sr = self.make_request(title="Tiling Fix")
        self.set_status(sr, ServiceRequestStatus.IN_PROGRESS, provider=self.provider)
        self.client.post(reverse("bookings:request-complete", args=[sr.id]))
        sr.refresh_from_db()

        customer_notif = self._get_notification(
            self.customer, NotificationType.JOB_COMPLETED
        )
        self.assertEqual(customer_notif.title, "Job Completed")
        self.assertIn("Tiling Fix", customer_notif.body)
        self.assertEqual(customer_notif.data["service_request_id"], str(sr.id))

        provider_notif = self._get_notification(
            self.provider, NotificationType.PAYMENT_SETTLED
        )
        self.assertEqual(provider_notif.title, "Payment Settled")
        self.assertEqual(provider_notif.data["service_request_id"], str(sr.id))

    # ── Customer cancels with provider (any → cancelled) ───────

    @patch(TASK_PATH)
    def test_cancelled_by_customer_notification_content(self, _mock_push):
        self.authenticate_customer()
        sr = self.assign_to_provider(self.make_request(title="Window Fix"))
        self.client.post(
            reverse("bookings:request-cancel", args=[sr.id]),
            {"reason": "No longer needed"},
        )

        notif = self._get_notification(
            self.provider, NotificationType.CANCELLED_BY_CUSTOMER
        )
        self.assertEqual(notif.title, "Request Cancelled")
        self.assertIn(self.customer.get_full_name(), notif.body)
        self.assertIn("Window Fix", notif.body)
        self.assertEqual(notif.data["service_request_id"], str(sr.id))

    # ── Provider cancels job (any → cancelled) ─────────────────

    @patch(TASK_PATH)
    def test_cancelled_by_provider_notification_content(self, _mock_push):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request(title="Roof Fix"))
        self.client.post(
            reverse("bookings:request-provider-cancel", args=[sr.id]),
            {"reason": "Emergency"},
        )

        notif = self._get_notification(
            self.customer, NotificationType.CANCELLED_BY_PROVIDER
        )
        self.assertEqual(notif.title, "Request Cancelled")
        self.assertIn("Roof Fix", notif.body)
        self.assertEqual(notif.data["service_request_id"], str(sr.id))

    # ── No push task fired when no provider on cancel ──────────

    @patch(TASK_PATH)
    def test_cancelling_pending_request_with_no_provider_sends_no_notification(
        self, mock_push
    ):
        self.authenticate_customer()
        sr = self.make_request()  # status=pending, provider=None
        self.client.post(reverse("bookings:request-cancel", args=[sr.id]), {})

        mock_push.assert_not_called()
        self.assertFalse(
            Notification.objects.filter(
                type=NotificationType.CANCELLED_BY_CUSTOMER
            ).exists()
        )
