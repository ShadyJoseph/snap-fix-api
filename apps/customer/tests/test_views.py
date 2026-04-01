from django.urls import reverse
from knox.models import AuthToken
from rest_framework import status
from rest_framework.test import APITestCase

from apps.customer.models import Customer
from apps.provider.choices import ProviderVerificationStatus
from apps.provider.models import Provider

# ──────────────────────────────
# Test constants
# ──────────────────────────────
TEST_PASSWORD = "secure-test-pass-123"


def create_customer(**kwargs):
    defaults = {
        "email": "customer@test.com",
        "first_name": "John",
        "last_name": "Doe",
        "phone": "01012345678",
        "password": TEST_PASSWORD,
    }
    defaults.update(kwargs)
    password = defaults.pop("password")
    customer = Customer(**defaults)
    customer.set_password(password)
    customer.save()
    return customer


class CustomerRegisterTests(APITestCase):
    url = reverse("customer-register")

    def test_register_success(self):
        payload = {
            "email": "new@test.com",
            "first_name": "John",
            "last_name": "Doe",
            "phone": "01012345678",
            "password": TEST_PASSWORD,
        }
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("token", response.data)
        self.assertEqual(response.data["customer"]["email"], payload["email"])
        self.assertTrue(Customer.objects.filter(email=payload["email"]).exists())

    def test_register_duplicate_email(self):
        create_customer(email="existing@test.com")
        payload = {
            "email": "existing@test.com",
            "first_name": "Jane",
            "last_name": "Doe",
            "phone": "01012345678",
            "password": TEST_PASSWORD,
        }
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_short_password(self):
        payload = {
            "email": "new@test.com",
            "first_name": "John",
            "last_name": "Doe",
            "phone": "01012345678",
            "password": "123",
        }
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_missing_fields(self):
        response = self.client.post(self.url, {"email": "new@test.com"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CustomerLoginTests(APITestCase):
    url = reverse("customer-login")

    def setUp(self):
        self.customer = create_customer(email="customer@test.com")

    def test_login_success(self):
        response = self.client.post(
            self.url,
            {
                "email": "customer@test.com",
                "password": TEST_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)
        self.assertEqual(response.data["customer"]["email"], "customer@test.com")

    def test_login_wrong_password(self):
        response = self.client.post(
            self.url,
            {
                "email": "customer@test.com",
                "password": "wrongpass",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_nonexistent_email(self):
        response = self.client.post(
            self.url,
            {
                "email": "nobody@test.com",
                "password": TEST_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_inactive_account(self):
        self.customer.is_active = False
        self.customer.save()
        response = self.client.post(
            self.url,
            {
                "email": "customer@test.com",
                "password": TEST_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CustomerLogoutTests(APITestCase):
    url = reverse("customer-logout")

    def setUp(self):
        self.customer = create_customer()
        _, self.token = AuthToken.objects.create(self.customer)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")

    def test_logout_success(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_logout_unauthenticated(self):
        self.client.credentials()
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class CustomerProfileTests(APITestCase):
    url = reverse("customer-profile")

    def setUp(self):
        self.customer = create_customer()
        _, self.token = AuthToken.objects.create(self.customer)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")

    def test_profile_success(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.customer.email)
        self.assertIn("wallet_balance", response.data)

    def test_profile_unauthenticated(self):
        self.client.credentials()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Helpers ───────────────────────────────────────────────────────────────────


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


class FavoritesTestCase(APITestCase):
    def setUp(self):
        self.customer = create_customer(email="fav_customer@test.com")
        self.provider = create_provider(email="fav_provider@test.com")
        self.client.force_authenticate(user=self.customer)

    def _toggle_url(self, provider=None):
        p = provider or self.provider
        return reverse("customer-favorite-toggle", args=[p.pk])


# ── Favorites: Toggle ─────────────────────────────────────────────────────────


class CustomerFavoriteToggleTests(FavoritesTestCase):
    def test_toggle_adds_provider_to_favorites(self):
        response = self.client.post(self._toggle_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_favorite"])
        self.assertTrue(
            self.customer.favorite_providers.filter(pk=self.provider.pk).exists()
        )

    def test_toggle_again_removes_provider_from_favorites(self):
        self.customer.favorite_providers.add(self.provider)
        response = self.client.post(self._toggle_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_favorite"])
        self.assertFalse(
            self.customer.favorite_providers.filter(pk=self.provider.pk).exists()
        )

    def test_response_includes_provider_id(self):
        response = self.client.post(self._toggle_url())
        self.assertEqual(str(response.data["provider_id"]), str(self.provider.pk))

    def test_nonexistent_provider_returns_404(self):
        import uuid

        url = reverse("customer-favorite-toggle", args=[uuid.uuid4()])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_provider_user_cannot_toggle(self):
        self.client.force_authenticate(user=self.provider)
        response = self.client.post(self._toggle_url())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self._toggle_url())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ── Favorites: List ───────────────────────────────────────────────────────────


class CustomerFavoritesListTests(FavoritesTestCase):
    url = reverse("customer-favorites-list")

    def test_returns_empty_when_no_favorites(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 0)

    def test_returns_favorited_providers(self):
        self.customer.favorite_providers.add(self.provider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(str(results[0]["id"]), str(self.provider.pk))

    def test_does_not_return_non_favorited_providers(self):
        other = create_provider(email="other_prov@test.com")
        self.customer.favorite_providers.add(self.provider)
        response = self.client.get(self.url)
        results = response.data.get("results", response.data)
        ids = [str(r["id"]) for r in results]
        self.assertIn(str(self.provider.pk), ids)
        self.assertNotIn(str(other.pk), ids)

    def test_rating_field_present_on_provider(self):
        self.customer.favorite_providers.add(self.provider)
        response = self.client.get(self.url)
        results = response.data.get("results", response.data)
        self.assertIn("rating", results[0])

    def test_provider_cannot_access(self):
        self.client.force_authenticate(user=self.provider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
