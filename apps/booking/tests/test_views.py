from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.booking.choices import CancelledBy, ServiceRequestStatus
from apps.booking.models import ServiceRequest
from apps.core.models import Category, Region
from apps.customer.models import Customer
from apps.provider.choices import ProviderVerificationStatus
from apps.provider.models import Provider

TEST_PASSWORD = "testpass123"  # noqa: S105


# ── Factories ─────────────────────────────────────────────────────────────────


def create_customer(**kwargs):
    defaults = {
        "email": "customer@test.com",
        "first_name": "Test",
        "last_name": "Customer",
        "password": TEST_PASSWORD,
        "is_active": True,
    }
    defaults.update(kwargs)
    return Customer.objects.create_user(**defaults)


def create_provider(**kwargs):
    defaults = {
        "email": "provider@test.com",
        "first_name": "Test",
        "last_name": "Provider",
        "password": TEST_PASSWORD,
        "is_active": True,
        "verification_status": ProviderVerificationStatus.VERIFIED,
    }
    defaults.update(kwargs)
    return Provider.objects.create_user(**defaults)


def create_category(**kwargs):
    defaults = {"name": "Plumbing", "slug": "plumbing", "is_active": True}
    defaults.update(kwargs)
    return Category.objects.get_or_create(slug=defaults["slug"], defaults=defaults)[0]


def create_region(**kwargs):
    defaults = {"name": "Cairo", "slug": "cairo", "code": "CAI", "is_active": True}
    defaults.update(kwargs)
    return Region.objects.get_or_create(slug=defaults["slug"], defaults=defaults)[0]


def create_service_request(customer, category, region, **kwargs):
    defaults = {
        "title": "Fix leaking pipe",
        "description": "Pipe under sink is leaking",
        "address": "123 Test St",
        "preferred_date": "2026-06-01",
        "preferred_time": "10:00:00",
        "is_urgent": False,
    }
    defaults.update(kwargs)
    return ServiceRequest.objects.create(
        customer=customer, category=category, region=region, **defaults
    )


# ── Base ──────────────────────────────────────────────────────────────────────


class BookingTestCase(APITestCase):
    def setUp(self):
        self.customer = create_customer()
        self.provider = create_provider()
        self.category = create_category()
        self.region = create_region()

    def authenticate_customer(self):
        self.client.force_authenticate(user=self.customer)

    def authenticate_provider(self):
        self.client.force_authenticate(user=self.provider)

    def make_request(self, **kwargs):
        return create_service_request(
            self.customer, self.category, self.region, **kwargs
        )

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


# ── Customer: Create & List ───────────────────────────────────────────────────


class CustomerRequestListCreateTests(BookingTestCase):
    url = reverse("request-list-create")

    def _valid_payload(self, **overrides):
        payload = {
            "category": self.category.id,
            "region": self.region.id,
            "address": "123 Test St",
            "title": "Fix leaking pipe",
            "description": "Pipe under sink is leaking",
            "preferred_date": "2026-06-01",
            "preferred_time": "10:00:00",
        }
        payload.update(overrides)
        return payload

    def test_create_success_returns_pending(self):
        self.authenticate_customer()
        response = self.client.post(self.url, self._valid_payload())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], ServiceRequestStatus.PENDING)
        self.assertIn("id", response.data)

    def test_create_assigns_customer_from_token(self):
        """Customer must come from the auth token, never from the request body."""
        self.authenticate_customer()
        response = self.client.post(self.url, self._valid_payload())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        sr = ServiceRequest.objects.get(id=response.data["id"])
        self.assertEqual(sr.customer, self.customer)

    def test_create_by_provider_returns_403(self):
        """Providers must not be able to create service requests."""
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

    def test_list_returns_only_own_requests(self):
        self.authenticate_customer()
        other = create_customer(email="other@test.com")
        self.make_request()
        create_service_request(other, self.category, self.region)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(self.get_results(response)), 1)

    def test_list_by_provider_returns_403(self):
        self.authenticate_provider()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_unauthenticated_returns_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_empty_when_no_requests(self):
        self.authenticate_customer()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(self.get_results(response)), 0)


# ── Customer: Detail ─────────────────────────────────────────────────────────


class CustomerRequestDetailTests(BookingTestCase):
    def test_get_own_request_success(self):
        self.authenticate_customer()
        sr = self.make_request()
        response = self.client.get(reverse("request-detail", args=[sr.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.data["id"]), str(sr.id))

    def test_get_other_customers_request_returns_404(self):
        other = create_customer(email="other@test.com")
        sr = create_service_request(other, self.category, self.region)
        self.authenticate_customer()
        response = self.client.get(reverse("request-detail", args=[sr.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_by_provider_returns_403(self):
        sr = self.make_request()
        self.authenticate_provider()
        response = self.client.get(reverse("request-detail", args=[sr.id]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_unauthenticated_returns_401(self):
        sr = self.make_request()
        response = self.client.get(reverse("request-detail", args=[sr.id]))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Customer: Cancel ─────────────────────────────────────────────────────────


class CustomerCancelTests(BookingTestCase):
    def _cancel_url(self, sr):
        return reverse("request-cancel", args=[sr.id])

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
        other = create_customer(email="other@test.com")
        sr = create_service_request(other, self.category, self.region)
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
    url = reverse("request-incoming")

    def test_returns_only_assigned_requests_for_this_provider(self):
        self.authenticate_provider()
        assigned = self.assign_to_provider(self.make_request())

        # same provider, different status — should NOT appear
        in_progress = self.make_request(title="In Progress Job")
        self.set_status(
            in_progress, ServiceRequestStatus.IN_PROGRESS, provider=self.provider
        )

        # different provider — should NOT appear
        other_provider = create_provider(email="other@provider.com")
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


# ── Provider: My Jobs ─────────────────────────────────────────────────────────


class ProviderMyJobsTests(BookingTestCase):
    url = reverse("request-my-jobs")

    def test_returns_all_own_jobs_across_statuses(self):
        self.authenticate_provider()
        confirmed = self.make_request(title="Confirmed Job")
        self.set_status(
            confirmed, ServiceRequestStatus.CONFIRMED, provider=self.provider
        )
        completed = self.make_request(title="Completed Job")
        self.set_status(
            completed, ServiceRequestStatus.COMPLETED, provider=self.provider
        )
        self.make_request(title="Unassigned")  # should NOT appear

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(self.get_results(response)), 2)

    def test_customer_cannot_access_my_jobs(self):
        self.authenticate_customer()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_returns_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Provider: Accept ─────────────────────────────────────────────────────────


class ProviderAcceptTests(BookingTestCase):
    def _accept_url(self, sr):
        return reverse("request-accept", args=[sr.id])

    def test_accept_assigned_request_transitions_to_confirmed(self):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(self._accept_url(sr))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CONFIRMED)
        self.assertIsNotNone(sr.confirmed_at)

    def test_cannot_accept_pending_request(self):
        self.authenticate_provider()
        sr = self.make_request()
        sr.provider = self.provider
        sr.save()
        response = self.client.post(self._accept_url(sr))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_accept_other_providers_request(self):
        self.authenticate_provider()
        other_provider = create_provider(email="other@provider.com")
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
        return reverse("request-decline", args=[sr.id])

    def test_decline_returns_request_to_pending_and_clears_provider(self):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(self._decline_url(sr), {"reason": "Not available"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.PENDING)
        self.assertIsNone(sr.provider)
        self.assertIsNone(sr.assigned_at)
        self.assertEqual(sr.decline_reason, "Not available")

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
        other_provider = create_provider(email="other@provider.com")
        sr = self.assign_to_provider(self.make_request(), provider=other_provider)
        response = self.client.post(self._decline_url(sr))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ── Provider: Start ───────────────────────────────────────────────────────────


class ProviderStartTests(BookingTestCase):
    def _start_url(self, sr):
        return reverse("request-start", args=[sr.id])

    def test_start_confirmed_request_transitions_to_in_progress(self):
        self.authenticate_provider()
        sr = self.make_request()
        self.set_status(sr, ServiceRequestStatus.CONFIRMED, provider=self.provider)
        response = self.client.post(self._start_url(sr))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.IN_PROGRESS)
        self.assertIsNotNone(sr.started_at)

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
        return reverse("request-complete", args=[sr.id])

    def _in_progress_request(self):
        sr = self.make_request()
        self.set_status(sr, ServiceRequestStatus.IN_PROGRESS, provider=self.provider)
        return sr

    def test_complete_with_final_price(self):
        self.authenticate_provider()
        sr = self._in_progress_request()
        response = self.client.post(self._complete_url(sr), {"final_price": "150.00"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)
        self.assertEqual(str(sr.final_price), "150.00")
        self.assertIsNotNone(sr.completed_at)

    def test_complete_without_price_is_allowed(self):
        self.authenticate_provider()
        sr = self._in_progress_request()
        response = self.client.post(self._complete_url(sr), {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)

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
        return reverse("request-provider-cancel", args=[sr.id])

    def test_cancel_assigned_request(self):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(self._cancel_url(sr), {"reason": "Emergency"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CANCELLED)
        self.assertEqual(sr.cancelled_by, CancelledBy.PROVIDER)
        self.assertEqual(sr.cancellation_reason, "Emergency")

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
        other_provider = create_provider(email="other@provider.com")
        sr = self.assign_to_provider(self.make_request(), provider=other_provider)
        response = self.client.post(self._cancel_url(sr))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ── Regression: Full Lifecycle ────────────────────────────────────────────────


class FullLifecycleRegressionTest(BookingTestCase):
    """
    Walks a request through every valid state.
    Guards against regressions that break the happy path.

        pending → assigned → confirmed → in_progress → completed
    """

    def test_full_happy_path(self):
        # 1. Customer creates request
        self.authenticate_customer()
        response = self.client.post(
            reverse("request-list-create"),
            {
                "category": self.category.id,
                "region": self.region.id,
                "address": "123 Test St",
                "title": "Full lifecycle test",
                "description": "Testing every step",
                "preferred_date": "2026-06-01",
                "preferred_time": "10:00:00",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        sr_id = response.data["id"]
        sr = ServiceRequest.objects.get(id=sr_id)
        self.assertEqual(sr.status, ServiceRequestStatus.PENDING)

        # 2. Admin assigns provider (direct model call)
        sr.assign(self.provider)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.ASSIGNED)
        self.assertEqual(sr.provider, self.provider)
        self.assertIsNotNone(sr.assigned_at)

        # 3. Provider accepts
        self.authenticate_provider()
        response = self.client.post(reverse("request-accept", args=[sr_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CONFIRMED)
        self.assertIsNotNone(sr.confirmed_at)

        # 4. Provider starts
        response = self.client.post(reverse("request-start", args=[sr_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.IN_PROGRESS)
        self.assertIsNotNone(sr.started_at)

        # 5. Provider completes
        response = self.client.post(
            reverse("request-complete", args=[sr_id]), {"final_price": "200.00"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)
        self.assertEqual(str(sr.final_price), "200.00")
        self.assertIsNotNone(sr.completed_at)

        # 6. Verify terminal — no further transitions allowed
        response = self.client.post(reverse("request-complete", args=[sr_id]), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.authenticate_customer()
        response = self.client.post(reverse("request-cancel", args=[sr_id]), {})
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
            reverse("request-decline", args=[sr.id]), {"reason": "Unavailable"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.PENDING)
        self.assertIsNone(sr.provider)
        self.assertEqual(sr.decline_reason, "Unavailable")

        # 3. Admin reassigns to second provider
        second_provider = create_provider(email="second@provider.com")
        sr.assign(second_provider)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.ASSIGNED)
        self.assertEqual(sr.provider, second_provider)

        # 4. Second provider accepts → starts → completes
        self.client.force_authenticate(user=second_provider)
        self.client.post(reverse("request-accept", args=[sr.id]))
        self.client.post(reverse("request-start", args=[sr.id]))
        response = self.client.post(
            reverse("request-complete", args=[sr.id]), {"final_price": "300.00"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)
        self.assertEqual(sr.provider, second_provider)


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
        response = self.client.post(reverse("request-complete", args=[sr.id]), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_skip_steps_confirmed_to_complete(self):
        self.authenticate_provider()
        sr = self.make_request()
        self.set_status(sr, ServiceRequestStatus.CONFIRMED, provider=self.provider)
        response = self.client.post(reverse("request-complete", args=[sr.id]), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_start_without_confirming_first(self):
        self.authenticate_provider()
        sr = self.assign_to_provider(self.make_request())
        response = self.client.post(reverse("request-start", args=[sr.id]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_accept_already_confirmed_request(self):
        self.authenticate_provider()
        sr = self.make_request()
        self.set_status(sr, ServiceRequestStatus.CONFIRMED, provider=self.provider)
        response = self.client.post(reverse("request-accept", args=[sr.id]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_cancel_completed_request(self):
        """COMPLETED is terminal — customer cannot cancel."""
        self.authenticate_customer()
        sr = self.make_request()
        self.set_status(sr, ServiceRequestStatus.COMPLETED)
        response = self.client.post(reverse("request-cancel", args=[sr.id]), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
