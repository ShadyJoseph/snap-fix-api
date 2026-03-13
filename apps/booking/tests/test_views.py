from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.booking.choices import CancelledBy, ServiceRequestStatus
from apps.booking.models import ServiceRequest
from apps.core.models import Category, Region
from apps.customer.models import Customer
from apps.provider.models import Provider

TEST_PASSWORD = "testpass123"  # noqa: S105


# ── Factories ─────────────────────────────────────────────────


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
    from apps.provider.choices import ProviderVerificationStatus

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
        "latitude": "30.044420",
        "longitude": "31.235712",
        "preferred_date": "2026-06-01",
        "preferred_time": "10:00:00",
        "is_urgent": False,
    }
    defaults.update(kwargs)
    return ServiceRequest.objects.create(
        customer=customer,
        category=category,
        region=region,
        **defaults,
    )


# ── Base Setup ────────────────────────────────────────────────


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


# ── Customer: Create & List ───────────────────────────────────


class CustomerRequestListCreateTests(BookingTestCase):
    url = reverse("request-list-create")

    def test_create_request_success(self):
        self.authenticate_customer()
        response = self.client.post(
            self.url,
            {
                "category": str(self.category.id),
                "region": str(self.region.id),
                "address": "123 Test St",
                "title": "Fix leaking pipe",
                "description": "Pipe under sink is leaking",
                "preferred_date": "2026-06-01",
                "preferred_time": "10:00:00",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], ServiceRequestStatus.PENDING)

    def test_create_request_unauthenticated(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_returns_only_own_requests(self):
        self.authenticate_customer()
        other_customer = create_customer(email="other@test.com")
        create_service_request(self.customer, self.category, self.region)
        create_service_request(other_customer, self.category, self.region)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = (
            response.data["results"] if "results" in response.data else response.data
        )
        self.assertEqual(len(results), 1)

    def test_list_unauthenticated(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Customer: Detail ─────────────────────────────────────────


class CustomerRequestDetailTests(BookingTestCase):
    def test_get_own_request(self):
        self.authenticate_customer()
        sr = create_service_request(self.customer, self.category, self.region)
        url = reverse("request-detail", args=[sr.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.data["id"]), str(sr.id))

    def test_cannot_get_other_customers_request(self):
        other = create_customer(email="other@test.com")
        sr = create_service_request(other, self.category, self.region)
        self.authenticate_customer()
        url = reverse("request-detail", args=[sr.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ── Customer: Cancel ─────────────────────────────────────────


class CustomerCancelTests(BookingTestCase):
    def test_cancel_pending_request(self):
        self.authenticate_customer()
        sr = create_service_request(self.customer, self.category, self.region)
        url = reverse("request-cancel", args=[sr.id])
        response = self.client.post(url, {"reason": "Changed my mind"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CANCELLED)
        self.assertEqual(sr.cancelled_by, CancelledBy.CUSTOMER)

    def test_cannot_cancel_completed_request(self):
        self.authenticate_customer()
        sr = create_service_request(self.customer, self.category, self.region)
        sr.status = ServiceRequestStatus.COMPLETED
        sr.save()
        url = reverse("request-cancel", args=[sr.id])
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_cancel_other_customers_request(self):
        other = create_customer(email="other@test.com")
        sr = create_service_request(other, self.category, self.region)
        self.authenticate_customer()
        url = reverse("request-cancel", args=[sr.id])
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ── Provider: Incoming ────────────────────────────────────────


class ProviderIncomingTests(BookingTestCase):
    url = reverse("request-incoming")

    def test_returns_only_assigned_requests(self):
        self.authenticate_provider()
        sr_assigned = create_service_request(self.customer, self.category, self.region)
        sr_assigned.provider = self.provider
        sr_assigned.status = ServiceRequestStatus.ASSIGNED
        sr_assigned.save()

        sr_pending = create_service_request(
            self.customer,
            self.category,
            self.region,
            title="Another request",
        )
        sr_pending.provider = self.provider
        sr_pending.status = ServiceRequestStatus.PENDING
        sr_pending.save()

        response = self.client.get(self.url)
        results = (
            response.data["results"] if "results" in response.data else response.data
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(str(results[0]["id"]), str(sr_assigned.id))

    def test_unauthenticated(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Provider: Accept ─────────────────────────────────────────


class ProviderAcceptTests(BookingTestCase):
    def _assigned_request(self):
        sr = create_service_request(self.customer, self.category, self.region)
        sr.provider = self.provider
        sr.status = ServiceRequestStatus.ASSIGNED
        sr.save()
        return sr

    def test_accept_assigned_request(self):
        self.authenticate_provider()
        sr = self._assigned_request()
        url = reverse("request-accept", args=[sr.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CONFIRMED)

    def test_cannot_accept_pending_request(self):
        self.authenticate_provider()
        sr = create_service_request(self.customer, self.category, self.region)
        sr.provider = self.provider
        sr.save()
        url = reverse("request-accept", args=[sr.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_accept_other_providers_request(self):
        self.authenticate_provider()
        other_provider = create_provider(email="other@provider.com")
        sr = create_service_request(self.customer, self.category, self.region)
        sr.provider = other_provider
        sr.status = ServiceRequestStatus.ASSIGNED
        sr.save()
        url = reverse("request-accept", args=[sr.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ── Provider: Decline ─────────────────────────────────────────


class ProviderDeclineTests(BookingTestCase):
    def test_decline_returns_to_pending(self):
        self.authenticate_provider()
        sr = create_service_request(self.customer, self.category, self.region)
        sr.provider = self.provider
        sr.status = ServiceRequestStatus.ASSIGNED
        sr.save()
        url = reverse("request-decline", args=[sr.id])
        response = self.client.post(url, {"reason": "Not available"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.PENDING)
        self.assertIsNone(sr.provider)


# ── Provider: Start ───────────────────────────────────────────


class ProviderStartTests(BookingTestCase):
    def test_start_confirmed_request(self):
        self.authenticate_provider()
        sr = create_service_request(self.customer, self.category, self.region)
        sr.provider = self.provider
        sr.status = ServiceRequestStatus.CONFIRMED
        sr.save()
        url = reverse("request-start", args=[sr.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.IN_PROGRESS)

    def test_cannot_start_assigned_request(self):
        self.authenticate_provider()
        sr = create_service_request(self.customer, self.category, self.region)
        sr.provider = self.provider
        sr.status = ServiceRequestStatus.ASSIGNED
        sr.save()
        url = reverse("request-start", args=[sr.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ── Provider: Complete ────────────────────────────────────────


class ProviderCompleteTests(BookingTestCase):
    def test_complete_in_progress_request(self):
        self.authenticate_provider()
        sr = create_service_request(self.customer, self.category, self.region)
        sr.provider = self.provider
        sr.status = ServiceRequestStatus.IN_PROGRESS
        sr.save()
        url = reverse("request-complete", args=[sr.id])
        response = self.client.post(url, {"final_price": "150.00"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)
        self.assertEqual(str(sr.final_price), "150.00")

    def test_complete_without_price(self):
        self.authenticate_provider()
        sr = create_service_request(self.customer, self.category, self.region)
        sr.provider = self.provider
        sr.status = ServiceRequestStatus.IN_PROGRESS
        sr.save()
        url = reverse("request-complete", args=[sr.id])
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.COMPLETED)

    def test_cannot_complete_confirmed_request(self):
        self.authenticate_provider()
        sr = create_service_request(self.customer, self.category, self.region)
        sr.provider = self.provider
        sr.status = ServiceRequestStatus.CONFIRMED
        sr.save()
        url = reverse("request-complete", args=[sr.id])
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ── Provider: Cancel ─────────────────────────────────────────


class ProviderCancelTests(BookingTestCase):
    def test_provider_cancel_assigned_request(self):
        self.authenticate_provider()
        sr = create_service_request(self.customer, self.category, self.region)
        sr.provider = self.provider
        sr.status = ServiceRequestStatus.ASSIGNED
        sr.save()
        url = reverse("request-provider-cancel", args=[sr.id])
        response = self.client.post(url, {"reason": "Emergency"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ServiceRequestStatus.CANCELLED)
        self.assertEqual(sr.cancelled_by, CancelledBy.PROVIDER)

    def test_cannot_cancel_completed_request(self):
        self.authenticate_provider()
        sr = create_service_request(self.customer, self.category, self.region)
        sr.provider = self.provider
        sr.status = ServiceRequestStatus.COMPLETED
        sr.save()
        url = reverse("request-provider-cancel", args=[sr.id])
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
