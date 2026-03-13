from django.urls import reverse
from knox.models import AuthToken
from rest_framework import status
from rest_framework.test import APITestCase

from apps.provider.choices import ProviderVerificationStatus
from apps.provider.models import Provider

TEST_PASSWORD = "TestPass123!"
TEST_PHONE = "01012345678"


def create_provider(active=True, verified=True, **kwargs):
    defaults = {
        "email": "provider@test.com",
        "first_name": "Jane",
        "last_name": "Smith",
        "phone": TEST_PHONE,
        "password": TEST_PASSWORD,
    }
    defaults.update(kwargs)

    password = defaults.pop("password")

    provider = Provider(
        **defaults,
        is_active=active,
        verification_status=(
            ProviderVerificationStatus.VERIFIED
            if verified
            else ProviderVerificationStatus.PENDING
        ),
    )

    provider.set_password(password)
    provider.save()

    return provider


class ProviderRegisterTests(APITestCase):
    url = reverse("provider-register")

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

        self.assertFalse(provider.is_active)
        self.assertEqual(
            provider.verification_status,
            ProviderVerificationStatus.PENDING,
        )

    def test_register_no_token_issued(self):
        payload = {
            "email": "new_provider@test.com",
            "first_name": "Jane",
            "last_name": "Smith",
            "phone": TEST_PHONE,
            "password": TEST_PASSWORD,
        }

        response = self.client.post(self.url, payload)

        self.assertNotIn("token", response.data)

    def test_register_duplicate_email(self):
        create_provider(email="existing@test.com")

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
    url = reverse("provider-login")

    def setUp(self):
        self.provider = create_provider(
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
        inactive = create_provider(
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
        unverified = create_provider(
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
    url = reverse("provider-logout")

    def setUp(self):
        self.provider = create_provider()
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
    url = reverse("provider-profile")

    def setUp(self):
        self.provider = create_provider()
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
