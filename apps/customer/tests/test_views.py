from django.urls import reverse
from knox.models import AuthToken
from rest_framework import status
from rest_framework.test import APITestCase

from apps.customer.models import Customer

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
