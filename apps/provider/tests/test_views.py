from django.urls import reverse
from knox.models import AuthToken
from rest_framework import status
from rest_framework.test import APITestCase

from apps.provider.choices import ProviderVerificationStatus
from apps.provider.models import Provider
from factories import make_image, make_provider

TEST_PASSWORD = "TestPass123!"  # noqa: S105
TEST_PHONE = "01012345678"


class ProviderRegisterTests(APITestCase):
    url = reverse("providers:provider-register")

    def test_register_success(self):
        payload = {
            "email": "new_provider@test.com",
            "first_name": "Jane",
            "last_name": "Smith",
            "phone": TEST_PHONE,
            "password": TEST_PASSWORD,
        }

        response = self.client.post(self.url, payload)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("message", response.data)

        provider = Provider.objects.get(email=payload["email"])

        # Newly registered providers are active so they can authenticate for the
        # self-service onboarding flow (Knox token is issued for this purpose).
        # Access to active-provider features is gated by verification_status=PENDING.
        self.assertTrue(provider.is_active)
        self.assertEqual(
            provider.verification_status,
            ProviderVerificationStatus.PENDING,
        )

    def test_register_returns_onboarding_token_not_plain_token(self):
        """Response key is 'onboarding_token', never the plain 'token' used by login."""
        payload = {
            "email": "new_provider@test.com",
            "first_name": "Jane",
            "last_name": "Smith",
            "phone": TEST_PHONE,
            "password": TEST_PASSWORD,
        }

        response = self.client.post(self.url, payload)

        self.assertIn("onboarding_token", response.data)
        self.assertNotIn("token", response.data)

    def test_register_duplicate_email(self):
        make_provider(email="existing@test.com")

        payload = {
            "email": "existing@test.com",
            "first_name": "Jane",
            "last_name": "Smith",
            "phone": TEST_PHONE,
            "password": TEST_PASSWORD,
        }

        response = self.client.post(self.url, payload)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_short_password(self):
        payload = {
            "email": "new_provider@test.com",
            "first_name": "Jane",
            "last_name": "Smith",
            "phone": TEST_PHONE,
            "password": "123",
        }

        response = self.client.post(self.url, payload)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ProviderLoginTests(APITestCase):
    url = reverse("providers:provider-login")

    def setUp(self):
        self.provider = make_provider(
            email="provider@test.com",
            password=TEST_PASSWORD,
            active=True,
            verified=True,
        )

    def test_login_success(self):
        response = self.client.post(
            self.url,
            {
                "email": "provider@test.com",
                "password": TEST_PASSWORD,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)
        self.assertIn("provider", response.data)

    def test_login_wrong_password(self):
        response = self.client.post(
            self.url,
            {
                "email": "provider@test.com",
                "password": "wrongpass",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_inactive_account(self):
        inactive = make_provider(
            email="inactive@test.com",
            password=TEST_PASSWORD,
            active=False,
            verified=False,
        )

        response = self.client.post(
            self.url,
            {
                "email": inactive.email,
                "password": TEST_PASSWORD,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_unverified_account(self):
        unverified = make_provider(
            email="unverified@test.com",
            password=TEST_PASSWORD,
            active=True,
            verified=False,
        )

        response = self.client.post(
            self.url,
            {
                "email": unverified.email,
                "password": TEST_PASSWORD,
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


class ProviderLogoutTests(APITestCase):
    url = reverse("providers:provider-logout")

    def setUp(self):
        self.provider = make_provider()
        _, self.token = AuthToken.objects.create(self.provider)

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")

    def test_logout_success(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_logout_unauthenticated(self):
        self.client.credentials()

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ProviderProfileTests(APITestCase):
    url = reverse("providers:provider-profile")

    def setUp(self):
        self.provider = make_provider()
        _, self.token = AuthToken.objects.create(self.provider)

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")

    def test_profile_success(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.provider.email)

        self.assertIn("verification_status", response.data)
        self.assertIn("completion_rate", response.data)

    def test_profile_unauthenticated(self):
        self.client.credentials()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ProviderProfileUpdateTests(APITestCase):
    url = reverse("providers:provider-profile")

    def setUp(self):
        self.provider = make_provider()
        _, token = AuthToken.objects.create(self.provider)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def test_patch_updates_allowed_fields(self):
        response = self.client.patch(
            self.url,
            {
                "first_name": "Updated",
                "last_name": "Provider",
                "business_name": "New Biz",
                "bio": "10 years experience",
                "hourly_rate": "120.00",
                "years_of_experience": 10,
                "is_available": False,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.first_name, "Updated")
        self.assertEqual(self.provider.business_name, "New Biz")
        self.assertFalse(self.provider.is_available)

    def test_patch_partial_updates_single_field(self):
        response = self.client.patch(self.url, {"bio": "New bio"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.bio, "New bio")

    def test_patch_is_available_toggle(self):
        original = self.provider.is_available
        response = self.client.patch(self.url, {"is_available": not original})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.is_available, not original)

    def test_patch_locked_fields_are_ignored(self):
        original_email = self.provider.email
        original_balance = self.provider.available_balance
        original_status = self.provider.verification_status
        self.client.patch(
            self.url,
            {
                "email": "hacked@test.com",
                "available_balance": "9999.00",
                "verification_status": "pending",
            },
        )
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.email, original_email)
        self.assertEqual(self.provider.available_balance, original_balance)
        self.assertEqual(self.provider.verification_status, original_status)

    def test_patch_profile_picture_upload(self):
        image = make_image("avatar.png")
        response = self.client.patch(
            self.url, {"profile_picture": image}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.provider.refresh_from_db()
        self.assertTrue(self.provider.profile_picture)

    def test_put_not_allowed(self):
        response = self.client.put(self.url, {"first_name": "X"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_patch_unauthenticated_returns_401(self):
        self.client.credentials()
        response = self.client.patch(self.url, {"first_name": "X"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
