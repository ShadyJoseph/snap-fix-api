import uuid

from django.contrib.gis.geos import Point
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

# Default pin-drop used by test factories (Cairo city centre).
_CAIRO = Point(31.2357, 30.0444, srid=4326)


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
        "floor_number": "3",
        "apartment_number": "12",
        "special_mark": "Blue door on the left",
        "location": _CAIRO,
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
        # Provider must have the category to see/pick matching requests.
        self.provider.categories.add(self.category)

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


# ── Shared helpers ────────────────────────────────────────────────────────────


def make_completed_request(customer, provider, category, region, **kwargs):
    """Create a service request already in COMPLETED state with a provider."""
    sr = create_service_request(customer, category, region, **kwargs)
    sr.status = ServiceRequestStatus.COMPLETED
    sr.provider = provider
    sr.save()
    return sr


def create_review(service_request, customer, provider, rating=4, comment="Good work"):
    from apps.booking.models import Review

    return Review.objects.create(
        service_request=service_request,
        customer=customer,
        provider=provider,
        rating=rating,
        comment=comment,
    )


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

    # ── POST (customer only) ──────────────────────────────────

    def test_create_success_returns_pending(self):
        self.authenticate_customer()
        response = self.client.post(self.url, self._valid_payload())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], ServiceRequestStatus.PENDING)
        self.assertIn("id", response.data)

    def test_create_assigns_customer_from_token(self):
        self.authenticate_customer()
        response = self.client.post(self.url, self._valid_payload())
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
        other = create_customer(email="other@test.com")
        self.make_request()
        create_service_request(other, self.category, self.region)
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
        create_review(sr, self.customer, self.provider, rating=5)
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
        create_review(sr, self.customer, self.provider, rating=3)
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
        other = create_customer(email="other@test.com")
        sr = create_service_request(other, self.category, self.region)
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


# ── Provider: Accept ─────────────────────────────────────────────────────────


class ProviderAcceptTests(BookingTestCase):
    def _accept_url(self, sr):
        return reverse("bookings:request-accept", args=[sr.id])

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
        return reverse("bookings:request-decline", args=[sr.id])

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
        self.assertIsNotNone(sr.declined_at)

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
        return reverse("bookings:request-start", args=[sr.id])

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
        return reverse("bookings:request-complete", args=[sr.id])

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
        return reverse("bookings:request-provider-cancel", args=[sr.id])

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

    def test_pick_pending_request_transitions_to_assigned(self):
        self.authenticate_provider()
        sr = self.make_request()
        response = self.client.post(self._pick_url(sr))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.ASSIGNED)
        self.assertEqual(sr.provider, self.provider)
        self.assertIsNotNone(sr.assigned_at)

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
        other_provider = create_provider(email="other@provider.com")
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
        second_provider = create_provider(email="second@provider.com")
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
    Walks a request through every valid state.
    Guards against regressions that break the happy path.

        pending → assigned → confirmed → in_progress → completed
    """

    def test_full_happy_path(self):
        # 1. Customer creates request
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
        response = self.client.post(reverse("bookings:request-accept", args=[sr_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CONFIRMED)
        self.assertIsNotNone(sr.confirmed_at)

        # 4. Provider starts
        response = self.client.post(reverse("bookings:request-start", args=[sr_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.IN_PROGRESS)
        self.assertIsNotNone(sr.started_at)

        # 5. Provider completes
        response = self.client.post(
            reverse("bookings:request-complete", args=[sr_id]),
            {"final_price": "200.00"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)
        self.assertEqual(str(sr.final_price), "200.00")
        self.assertIsNotNone(sr.completed_at)

        # 6. Verify terminal — no further transitions allowed
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
        self.assertIsNotNone(
            sr.declined_at
        )  # audit trail stamped, request still pending

        # 3. Admin reassigns to second provider
        second_provider = create_provider(email="second@provider.com")
        sr.assign(second_provider)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.ASSIGNED)
        self.assertEqual(sr.provider, second_provider)

        # 4. Second provider accepts → starts → completes
        self.client.force_authenticate(user=second_provider)
        self.client.post(reverse("bookings:request-accept", args=[sr.id]))
        self.client.post(reverse("bookings:request-start", args=[sr.id]))
        response = self.client.post(
            reverse("bookings:request-complete", args=[sr.id]),
            {"final_price": "300.00"},
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
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

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

        pending → (provider picks) → assigned → confirmed → in_progress → completed
    """

    def test_pick_then_full_lifecycle(self):
        # 1. Customer creates request
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

        # 6. Standard flow: accept → start → complete
        self.client.post(reverse("bookings:request-accept", args=[sr_id]))
        self.client.post(reverse("bookings:request-start", args=[sr_id]))
        response = self.client.post(
            reverse("bookings:request-complete", args=[sr_id]),
            {"final_price": "250.00"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        sr = ServiceRequest.objects.get(id=sr_id)
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)
        self.assertEqual(sr.provider, self.provider)


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
        create_review(sr, self.customer, self.provider, rating=4)
        response = self.client.post(
            self._rate_url(sr), {"rating": 1, "comment": "Different"}
        )
        # Returns existing review, not the new payload
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
        other = create_customer(email="other2@test.com")
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
        create_review(sr, self.customer, self.provider, rating=4, comment="Solid")
        response = self.client.get(self._detail_url(sr))
        self.assertEqual(response.data["review"]["rating"], 4)
        self.assertEqual(response.data["review"]["comment"], "Solid")

    def test_customer_other_request_returns_404(self):
        other = create_customer(email="other4@test.com")
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
        create_review(sr, self.customer, self.provider, rating=2, comment="Meh")
        response = self.client.get(self._detail_url(sr))
        self.assertEqual(response.data["review"]["rating"], 2)

    def test_provider_other_job_returns_404(self):
        other_provider = create_provider(email="other6@provider.com")
        sr = make_completed_request(
            self.customer, other_provider, self.category, self.region
        )
        self.authenticate_provider()
        response = self.client.get(self._detail_url(sr))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ── Cross-role isolation ──────────────────────────────────────────────────

    def test_provider_token_on_customer_request_returns_404(self):
        # Provider queries are scoped to their assigned jobs — customer's request is invisible
        sr = make_completed_request(
            self.customer, self.provider, self.category, self.region
        )
        other_provider = create_provider(email="cross@provider.com")
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
        return self.client.post(self.url, payload)

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
        self.other_category = create_category(name="Electrical", slug="electrical")

    def test_only_matching_category_requests_shown(self):
        self.authenticate_provider()
        matching = self.make_request(title="Plumbing Job")
        other_sr = create_service_request(
            self.customer, self.other_category, self.region, title="Electrical Job"
        )

        response = self.client.get(self.url)
        ids = [str(r["id"]) for r in self.get_results(response)]
        self.assertIn(str(matching.id), ids)
        self.assertNotIn(str(other_sr.id), ids)

    def test_provider_with_no_categories_sees_empty_pool(self):
        provider_no_cats = create_provider(email="nocats@provider.com")
        self.client.force_authenticate(user=provider_no_cats)
        self.make_request()
        response = self.client.get(self.url)
        self.assertEqual(len(self.get_results(response)), 0)

    def test_provider_with_multiple_categories_sees_all_matches(self):
        self.provider.categories.add(self.other_category)
        self.authenticate_provider()
        plumbing = self.make_request(title="Plumbing Job")
        electrical = create_service_request(
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
        self.other_category = create_category(name="Electrical", slug="electrical")

    def test_pick_request_in_other_category_returns_404(self):
        """Direct URL manipulation must not bypass the category guard."""
        self.authenticate_provider()
        other_sr = create_service_request(
            self.customer, self.other_category, self.region
        )
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
        # Provider ~30 km north — at 30 km/h should be ~60 min
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
