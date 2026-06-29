"""
Self-Service Provider Onboarding — Unit & Integration Tests
============================================================
Run with:
    python manage.py test apps.provider.tests.test_self_service_onboarding -v 2

Test suites
-----------
1. RegistrationFlowTests        — register endpoint issues a token, new is_active semantics
2. PermissionTests              — IsAwaitingOnboarding gate
3. CanResubmitPropertyTests     — model property logic
4. ResubmitMethodTests          — resubmit() FSM transition
5. RejectCooldownTests          — reject() sets can_resubmit_after
6. OnboardingStatusViewTests    — GET /onboarding/status/
7. PersonalInfoViewTests        — PATCH /onboarding/personal/
8. DocumentsViewTests           — PATCH /onboarding/documents/
9. SubmitViewTests              — POST /onboarding/submit/
10. SubmitValidationTests       — missing-field guards
11. NotificationTests           — onboarding notification helpers
12. AdminNotificationHookTests  — notifications fired by save_model
13. AiValidationFallbackTests   — ai_validation.py error paths
14. TaskTests                   — validate_onboarding_documents Celery task
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.notifications.choices import NotificationType
from apps.notifications.models import Notification
from apps.provider.choices import (
    AIValidationStatus,
    OnboardingStatus,
    ProviderVerificationStatus,
)
from apps.provider.models import Provider, ProviderOnboarding
from factories import (
    make_category,
    make_image,
    make_onboarding,
    make_provider,
    make_region,
    make_staff,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _auth_client(provider: Provider) -> APIClient:
    """Return an APIClient authenticated as the given provider via Knox token."""
    from knox.models import AuthToken

    _, token = AuthToken.objects.create(provider)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    return client


def _make_pending_provider(**kwargs) -> Provider:
    """Pending provider (active, verification_status=PENDING)."""
    return make_provider(active=True, verified=False, **kwargs)


def _make_draft_onboarding(provider, region, category) -> ProviderOnboarding:
    """Create a minimal DRAFT application for the given provider."""
    return ProviderOnboarding.objects.create(
        applicant=provider,
        first_name=provider.first_name,
        last_name=provider.last_name,
        email=provider.email,
        phone=provider.phone,
        status=OnboardingStatus.DRAFT,
        ai_validation_status=AIValidationStatus.PENDING,
    )


def _make_complete_draft(provider, region, category) -> ProviderOnboarding:
    """DRAFT with all required fields — ready to submit."""
    dob = date.today() - timedelta(days=365 * 25)
    return ProviderOnboarding.objects.create(
        applicant=provider,
        first_name=provider.first_name,
        last_name=provider.last_name,
        email=provider.email,
        phone=provider.phone,
        date_of_birth=dob,
        address="123 Cairo St",
        region=region,
        category=category,
        hourly_rate=Decimal("150.00"),
        years_of_experience=3,
        nid_front=make_image("nid_front.png"),
        nid_back=make_image("nid_back.png"),
        police_clearance_certificate=make_image("pcc.png"),
        status=OnboardingStatus.DRAFT,
        ai_validation_status=AIValidationStatus.PENDING,
    )


# ═════════════════════════════════════════════════════════════════════════════
# 1. Registration Flow
# ═════════════════════════════════════════════════════════════════════════════


class RegistrationFlowTests(TestCase):
    def test_register_creates_active_pending_provider(self):
        """Post-fix: providers are active (can authenticate) but PENDING (limited access)."""
        client = APIClient()
        res = client.post(
            "/api/v1/providers/register/",
            {
                "first_name": "Jane",
                "last_name": "Smith",
                "email": "jane@test.com",
                "phone": "01012345678",
                "password": "secure1234!!",
            },
        )
        self.assertEqual(res.status_code, 201)
        provider = Provider.objects.get(email="jane@test.com")
        self.assertTrue(provider.is_active)
        self.assertEqual(
            provider.verification_status, ProviderVerificationStatus.PENDING
        )

    def test_register_returns_onboarding_token(self):
        """Registration response includes an onboarding_token for subsequent API calls."""
        client = APIClient()
        res = client.post(
            "/api/v1/providers/register/",
            {
                "first_name": "Jane",
                "last_name": "Smith",
                "email": "jane2@test.com",
                "phone": "01012345678",
                "password": "secure1234!!",
            },
        )
        self.assertEqual(res.status_code, 201)
        self.assertIn("onboarding_token", res.data)

    def test_pending_provider_cannot_use_main_login(self):
        """PENDING providers are blocked from the full login endpoint."""
        password = "pass1234!!"  # noqa: S106
        make_provider(
            email="pending@test.com", active=True, verified=False, password=password
        )
        client = APIClient()
        res = client.post(
            "/api/v1/providers/login/",
            {
                "email": "pending@test.com",
                "password": "pass1234!!",
            },
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("review", str(res.data).lower())

    def test_verified_provider_can_login(self):
        """VERIFIED providers can use the main login endpoint."""
        password = "pass1234!!"  # noqa: S106
        make_provider(
            email="verified@test.com", active=True, verified=True, password=password
        )
        client = APIClient()
        res = client.post(
            "/api/v1/providers/login/",
            {
                "email": "verified@test.com",
                "password": "pass1234!!",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("token", res.data)


# ═════════════════════════════════════════════════════════════════════════════
# 2. Permission — IsAwaitingOnboarding
# ═════════════════════════════════════════════════════════════════════════════


class PermissionTests(TestCase):
    def setUp(self):
        self.region = make_region()
        self.category = make_category()

    def test_pending_provider_can_access_onboarding_endpoints(self):
        """PENDING provider with Knox token can reach the personal-info endpoint."""
        provider = _make_pending_provider()
        client = _auth_client(provider)
        res = client.patch(
            "/api/v1/providers/onboarding/personal/",
            {
                "date_of_birth": "1995-01-01",
                "address": "Cairo",
                "region": self.region.pk,
                "category": self.category.pk,
                "hourly_rate": "100.00",
            },
        )
        # May be 200 or 400 (missing fields) but NOT 401/403
        self.assertNotIn(res.status_code, [401, 403])

    def test_verified_provider_blocked_from_onboarding(self):
        """VERIFIED (approved) provider cannot modify onboarding application."""
        provider = make_provider(active=True, verified=True)
        client = _auth_client(provider)
        res = client.patch(
            "/api/v1/providers/onboarding/personal/", {"address": "Cairo"}
        )
        self.assertEqual(res.status_code, 403)

    def test_unauthenticated_user_blocked(self):
        """Unauthenticated request is blocked."""
        client = APIClient()
        res = client.patch(
            "/api/v1/providers/onboarding/personal/", {"address": "Cairo"}
        )
        self.assertEqual(res.status_code, 401)


# ═════════════════════════════════════════════════════════════════════════════
# 3. can_resubmit Property
# ═════════════════════════════════════════════════════════════════════════════


class CanResubmitPropertyTests(TestCase):
    def setUp(self):
        self.region = make_region()
        self.category = make_category()
        self.staff = make_staff()

    def test_returns_false_when_not_rejected(self):
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)
        self.assertFalse(app.can_resubmit)

    def test_returns_false_when_rejected_but_cooldown_not_expired(self):
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(self.staff)
        app.reject(self.staff, reason="Bad docs")
        app.refresh_from_db()
        # can_resubmit_after is ~30 days in the future
        self.assertFalse(app.can_resubmit)

    def test_returns_true_when_rejected_and_cooldown_expired(self):
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(self.staff)
        app.reject(self.staff, reason="Bad docs")
        # Manually set cooldown to the past
        app.can_resubmit_after = timezone.now() - timedelta(days=1)
        app.save(update_fields=["can_resubmit_after"])
        self.assertTrue(app.can_resubmit)

    def test_returns_false_when_can_resubmit_after_is_none(self):
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.status = OnboardingStatus.REJECTED
        app.can_resubmit_after = None
        app.save(update_fields=["status", "can_resubmit_after"])
        self.assertFalse(app.can_resubmit)


# ═════════════════════════════════════════════════════════════════════════════
# 4. resubmit() Method
# ═════════════════════════════════════════════════════════════════════════════


class ResubmitMethodTests(TestCase):
    def setUp(self):
        self.region = make_region()
        self.category = make_category()
        self.staff = make_staff()

    def _rejected_app(self):
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(self.staff)
        app.reject(self.staff, reason="Incomplete documents")
        app.can_resubmit_after = timezone.now() - timedelta(days=1)
        app.save(update_fields=["can_resubmit_after"])
        app.refresh_from_db()
        return app

    def test_resubmit_resets_to_draft(self):
        app = self._rejected_app()
        app.resubmit()
        app.refresh_from_db()
        self.assertEqual(app.status, OnboardingStatus.DRAFT)

    def test_resubmit_clears_rejection_fields(self):
        app = self._rejected_app()
        app.resubmit()
        app.refresh_from_db()
        self.assertEqual(app.rejection_reason, "")
        self.assertEqual(app.change_requests, "")
        self.assertIsNone(app.can_resubmit_after)
        self.assertIsNone(app.rejected_at)
        self.assertIsNone(app.reviewed_at)

    def test_resubmit_resets_ai_validation(self):
        app = self._rejected_app()
        app.ai_validation_status = AIValidationStatus.FAILED
        app.ai_validation_report = {"status": "failed", "issues": ["bad doc"]}
        app.save(update_fields=["ai_validation_status", "ai_validation_report"])
        app.resubmit()
        app.refresh_from_db()
        self.assertEqual(app.ai_validation_status, AIValidationStatus.PENDING)
        self.assertEqual(app.ai_validation_report, {})

    def test_resubmit_raises_when_not_rejected(self):
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)
        with self.assertRaises(ValueError):
            app.resubmit()

    def test_resubmit_raises_when_cooldown_not_expired(self):
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(self.staff)
        app.reject(self.staff, reason="test")
        # cooldown is 30 days in the future
        with self.assertRaises(ValueError):
            app.resubmit()


# ═════════════════════════════════════════════════════════════════════════════
# 5. reject() Sets Cooldown
# ═════════════════════════════════════════════════════════════════════════════


class RejectCooldownTests(TestCase):
    def setUp(self):
        self.region = make_region()
        self.category = make_category()
        self.staff = make_staff()

    def test_reject_sets_can_resubmit_after(self):
        from constance import config as constance_config

        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(self.staff)
        before = timezone.now()
        app.reject(self.staff, reason="Bad docs")
        app.refresh_from_db()

        self.assertIsNotNone(app.can_resubmit_after)
        delta = app.can_resubmit_after - before
        self.assertAlmostEqual(
            delta.days, constance_config.ONBOARDING_REJECTION_COOLDOWN_DAYS, delta=1
        )

    def test_reject_sets_rejected_at(self):
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(self.staff)
        before = timezone.now()
        app.reject(self.staff, reason="test")
        app.refresh_from_db()
        self.assertIsNotNone(app.rejected_at)
        self.assertGreaterEqual(app.rejected_at, before)


# ═════════════════════════════════════════════════════════════════════════════
# 6. OnboardingStatusView — GET /onboarding/status/
# ═════════════════════════════════════════════════════════════════════════════


class OnboardingStatusViewTests(TestCase):
    def setUp(self):
        self.region = make_region()
        self.category = make_category()

    def test_404_when_no_application_exists(self):
        provider = _make_pending_provider()
        client = _auth_client(provider)
        res = client.get("/api/v1/providers/onboarding/status/")
        self.assertEqual(res.status_code, 404)

    def test_returns_draft_status(self):
        provider = _make_pending_provider()
        _make_draft_onboarding(provider, self.region, self.category)
        client = _auth_client(provider)
        res = client.get("/api/v1/providers/onboarding/status/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], OnboardingStatus.DRAFT)

    def test_returns_ai_report_summary_when_present(self):
        provider = _make_pending_provider()
        app = _make_draft_onboarding(provider, self.region, self.category)
        app.ai_validation_report = {
            "status": "flagged",
            "issues": ["blurry NID"],
            "overall_confidence": 0.4,
        }
        app.save(update_fields=["ai_validation_report"])
        client = _auth_client(provider)
        res = client.get("/api/v1/providers/onboarding/status/")
        self.assertEqual(res.status_code, 200)
        summary = res.data["ai_report_summary"]
        self.assertIsNotNone(summary)
        self.assertEqual(summary["status"], "flagged")
        self.assertIn("blurry NID", summary["issues"])

    def test_returns_null_ai_report_when_empty(self):
        provider = _make_pending_provider()
        _make_draft_onboarding(provider, self.region, self.category)
        client = _auth_client(provider)
        res = client.get("/api/v1/providers/onboarding/status/")
        self.assertIsNone(res.data["ai_report_summary"])

    def test_403_for_non_provider_authenticated_user(self):
        """Customers or staff can't access this endpoint."""
        from knox.models import AuthToken

        from factories import make_customer

        customer = make_customer()
        _, token = AuthToken.objects.create(customer)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        res = client.get("/api/v1/providers/onboarding/status/")
        self.assertEqual(res.status_code, 403)


# ═════════════════════════════════════════════════════════════════════════════
# 7. PersonalInfoView — PATCH /onboarding/personal/
# ═════════════════════════════════════════════════════════════════════════════


class PersonalInfoViewTests(TestCase):
    def setUp(self):
        self.region = make_region()
        self.category = make_category()

    def _payload(self, **overrides):
        base = {
            "date_of_birth": "1995-06-15",
            "address": "456 Giza St",
            "region": self.region.pk,
            "category": self.category.pk,
            "hourly_rate": "200.00",
            "years_of_experience": 5,
            "bio": "Experienced plumber",
        }
        base.update(overrides)
        return base

    def test_creates_draft_on_first_call(self):
        provider = _make_pending_provider()
        client = _auth_client(provider)
        res = client.patch("/api/v1/providers/onboarding/personal/", self._payload())
        self.assertEqual(res.status_code, 200)
        self.assertTrue(ProviderOnboarding.objects.filter(applicant=provider).exists())
        app = ProviderOnboarding.objects.get(applicant=provider)
        self.assertEqual(app.status, OnboardingStatus.DRAFT)

    def test_identity_fields_come_from_provider_account(self):
        """first_name, last_name, email, phone are always taken from the Provider."""
        provider = _make_pending_provider(
            first_name="Ali", last_name="Hasan", phone="01012345678"
        )
        client = _auth_client(provider)
        client.patch("/api/v1/providers/onboarding/personal/", self._payload())
        app = ProviderOnboarding.objects.get(applicant=provider)
        self.assertEqual(app.first_name, "Ali")
        self.assertEqual(app.last_name, "Hasan")
        self.assertEqual(app.email, provider.email)
        self.assertEqual(app.phone, "01012345678")

    def test_updates_existing_draft(self):
        provider = _make_pending_provider()
        _make_draft_onboarding(provider, self.region, self.category)
        client = _auth_client(provider)
        res = client.patch(
            "/api/v1/providers/onboarding/personal/", {"bio": "Updated bio"}
        )
        self.assertEqual(res.status_code, 200)
        app = ProviderOnboarding.objects.get(applicant=provider)
        self.assertEqual(app.bio, "Updated bio")

    def test_blocks_underage_applicant(self):
        provider = _make_pending_provider()
        client = _auth_client(provider)
        res = client.patch(
            "/api/v1/providers/onboarding/personal/",
            self._payload(
                date_of_birth=(date.today() - timedelta(days=365 * 17)).isoformat()
            ),
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("18", str(res.data))

    def test_blocks_update_when_status_is_under_review(self):
        provider = _make_pending_provider()
        staff = make_staff()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(staff)
        # Application is now UNDER_REVIEW — not editable
        client = _auth_client(provider)
        res = client.patch("/api/v1/providers/onboarding/personal/", {"bio": "nope"})
        self.assertEqual(res.status_code, 400)

    def test_allows_update_when_changes_required(self):
        provider = _make_pending_provider()
        staff = make_staff()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(staff)
        app.request_changes(staff, change_requests="Clearer photo please")
        client = _auth_client(provider)
        res = client.patch("/api/v1/providers/onboarding/personal/", {"bio": "Updated"})
        self.assertEqual(res.status_code, 200)

    def test_rejected_cooldown_not_expired_returns_403(self):
        provider = _make_pending_provider()
        staff = make_staff()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(staff)
        app.reject(staff, reason="Docs incomplete")
        # cooldown not expired yet
        client = _auth_client(provider)
        res = client.patch("/api/v1/providers/onboarding/personal/", {"bio": "retry"})
        self.assertEqual(res.status_code, 403)
        self.assertIn("can_resubmit_after", res.data)

    def test_rejected_expired_cooldown_resets_to_draft(self):
        provider = _make_pending_provider()
        staff = make_staff()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(staff)
        app.reject(staff, reason="Docs incomplete")
        # Expire the cooldown
        app.can_resubmit_after = timezone.now() - timedelta(hours=1)
        app.save(update_fields=["can_resubmit_after"])

        client = _auth_client(provider)
        res = client.patch("/api/v1/providers/onboarding/personal/", {"bio": "new bio"})
        self.assertEqual(res.status_code, 200)
        app.refresh_from_db()
        self.assertEqual(app.status, OnboardingStatus.DRAFT)


# ═════════════════════════════════════════════════════════════════════════════
# 8. DocumentsView — PATCH /onboarding/documents/
# ═════════════════════════════════════════════════════════════════════════════


class DocumentsViewTests(TestCase):
    def setUp(self):
        self.region = make_region()
        self.category = make_category()

    def test_uploads_nid_front(self):
        provider = _make_pending_provider()
        _make_draft_onboarding(provider, self.region, self.category)
        client = _auth_client(provider)
        res = client.patch(
            "/api/v1/providers/onboarding/documents/",
            {"nid_front": make_image("front.png")},
            format="multipart",
        )
        self.assertEqual(res.status_code, 200)
        app = ProviderOnboarding.objects.get(applicant=provider)
        self.assertTrue(bool(app.nid_front))

    def test_404_when_no_draft_exists(self):
        provider = _make_pending_provider()
        client = _auth_client(provider)
        res = client.patch(
            "/api/v1/providers/onboarding/documents/",
            {"nid_front": make_image()},
            format="multipart",
        )
        self.assertEqual(res.status_code, 404)

    def test_blocks_upload_when_application_is_pending(self):
        provider = _make_pending_provider()
        staff = make_staff()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(staff)
        client = _auth_client(provider)
        res = client.patch(
            "/api/v1/providers/onboarding/documents/",
            {"nid_front": make_image()},
            format="multipart",
        )
        self.assertEqual(res.status_code, 400)

    def test_allows_upload_when_changes_required(self):
        provider = _make_pending_provider()
        staff = make_staff()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(staff)
        app.request_changes(staff, change_requests="Better NID photo")
        client = _auth_client(provider)
        res = client.patch(
            "/api/v1/providers/onboarding/documents/",
            {"nid_front": make_image("new_front.png")},
            format="multipart",
        )
        self.assertEqual(res.status_code, 200)


# ═════════════════════════════════════════════════════════════════════════════
# 9. SubmitView — POST /onboarding/submit/
# ═════════════════════════════════════════════════════════════════════════════


class SubmitViewTests(TestCase):
    def setUp(self):
        self.region = make_region()
        self.category = make_category()

    @patch("apps.provider.tasks.validate_onboarding_documents.delay")
    def test_submit_sets_status_to_pending(self, mock_delay):
        provider = _make_pending_provider()
        _make_complete_draft(provider, self.region, self.category)
        client = _auth_client(provider)
        res = client.post("/api/v1/providers/onboarding/submit/")
        self.assertEqual(res.status_code, 200)
        app = ProviderOnboarding.objects.get(applicant=provider)
        self.assertEqual(app.status, OnboardingStatus.PENDING)

    @patch("apps.provider.tasks.validate_onboarding_documents.delay")
    def test_submit_enqueues_ai_validation_task(self, mock_delay):
        provider = _make_pending_provider()
        app = _make_complete_draft(provider, self.region, self.category)
        client = _auth_client(provider)
        with self.captureOnCommitCallbacks(execute=True):
            client.post("/api/v1/providers/onboarding/submit/")
        mock_delay.assert_called_once_with(str(app.pk))

    @patch("apps.provider.tasks.validate_onboarding_documents.delay")
    def test_submit_resets_ai_validation_status_to_pending(self, mock_delay):
        provider = _make_pending_provider()
        app = _make_complete_draft(provider, self.region, self.category)
        # Simulate a previous failed validation
        app.ai_validation_status = AIValidationStatus.FAILED
        app.save(update_fields=["ai_validation_status"])
        client = _auth_client(provider)
        client.post("/api/v1/providers/onboarding/submit/")
        app.refresh_from_db()
        self.assertEqual(app.ai_validation_status, AIValidationStatus.PENDING)

    def test_submit_404_when_no_application(self):
        provider = _make_pending_provider()
        client = _auth_client(provider)
        res = client.post("/api/v1/providers/onboarding/submit/")
        self.assertEqual(res.status_code, 404)

    @patch("apps.provider.tasks.validate_onboarding_documents.delay")
    def test_submit_allowed_from_changes_required(self, mock_delay):
        provider = _make_pending_provider()
        app = _make_complete_draft(provider, self.region, self.category)
        app.status = OnboardingStatus.CHANGES_REQUIRED
        app.save(update_fields=["status"])
        client = _auth_client(provider)
        res = client.post("/api/v1/providers/onboarding/submit/")
        self.assertEqual(res.status_code, 200)

    def test_submit_blocked_when_already_pending(self):
        provider = _make_pending_provider()
        app = _make_complete_draft(provider, self.region, self.category)
        app.status = OnboardingStatus.PENDING
        app.save(update_fields=["status"])
        client = _auth_client(provider)
        res = client.post("/api/v1/providers/onboarding/submit/")
        self.assertEqual(res.status_code, 400)


# ═════════════════════════════════════════════════════════════════════════════
# 10. Submit Validation — missing required fields
# ═════════════════════════════════════════════════════════════════════════════


class SubmitValidationTests(TestCase):
    def setUp(self):
        self.region = make_region()
        self.category = make_category()

    def test_submit_fails_without_date_of_birth(self):
        provider = _make_pending_provider()
        app = _make_complete_draft(provider, self.region, self.category)
        app.date_of_birth = None
        app.save(update_fields=["date_of_birth"])
        client = _auth_client(provider)
        res = client.post("/api/v1/providers/onboarding/submit/")
        self.assertEqual(res.status_code, 400)
        self.assertIn("date_of_birth", str(res.data))

    def test_submit_fails_without_region(self):
        provider = _make_pending_provider()
        app = _make_complete_draft(provider, self.region, self.category)
        app.region = None
        app.save(update_fields=["region"])
        client = _auth_client(provider)
        res = client.post("/api/v1/providers/onboarding/submit/")
        self.assertEqual(res.status_code, 400)
        self.assertIn("region", str(res.data))

    def test_submit_fails_without_nid_front(self):
        provider = _make_pending_provider()
        app = _make_complete_draft(provider, self.region, self.category)
        app.nid_front = None
        app.save(update_fields=["nid_front"])
        client = _auth_client(provider)
        res = client.post("/api/v1/providers/onboarding/submit/")
        self.assertEqual(res.status_code, 400)
        self.assertIn("nid_front", str(res.data))

    def test_submit_fails_without_police_clearance(self):
        provider = _make_pending_provider()
        app = _make_complete_draft(provider, self.region, self.category)
        app.police_clearance_certificate = None
        app.save(update_fields=["police_clearance_certificate"])
        client = _auth_client(provider)
        res = client.post("/api/v1/providers/onboarding/submit/")
        self.assertEqual(res.status_code, 400)
        self.assertIn("police_clearance_certificate", str(res.data))

    def test_missing_fields_response_lists_all_missing(self):
        """Response includes all missing fields, not just the first one."""
        provider = _make_pending_provider()
        # Create an almost-empty draft
        _make_draft_onboarding(provider, self.region, self.category)
        client = _auth_client(provider)
        res = client.post("/api/v1/providers/onboarding/submit/")
        self.assertEqual(res.status_code, 400)
        missing = res.data.get("missing_fields", [])
        self.assertIn("date_of_birth", missing)
        self.assertIn("nid_front", missing)
        self.assertIn("nid_back", missing)
        self.assertIn("police_clearance_certificate", missing)


# ═════════════════════════════════════════════════════════════════════════════
# 11. Notification Helpers
# ═════════════════════════════════════════════════════════════════════════════


class NotificationTests(TestCase):
    def setUp(self):
        self.region = make_region()
        self.category = make_category()
        self.staff = make_staff()

    def _approved_app(self):
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(self.staff)
        app.approve(self.staff)
        app.refresh_from_db()
        return app

    def _rejected_app(self):
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(self.staff)
        app.reject(self.staff, reason="Fraudulent documents.")
        app.refresh_from_db()
        return app

    def _changes_app(self):
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(self.staff)
        app.request_changes(self.staff, change_requests="Clearer photo needed.")
        app.refresh_from_db()
        return app

    @patch("apps.notifications.tasks.send_push_notification.delay")
    def test_approved_notification_saved_to_db(self, _mock):
        from apps.notifications.service import notify_provider_onboarding_approved

        app = self._approved_app()
        notify_provider_onboarding_approved(app)
        notif = Notification.objects.filter(
            recipient=app.applicant,
            type=NotificationType.ONBOARDING_APPROVED,
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn("approved", notif.title.lower())

    @patch("apps.notifications.tasks.send_push_notification.delay")
    def test_rejected_notification_includes_reason(self, _mock):
        from apps.notifications.service import notify_provider_onboarding_rejected

        app = self._rejected_app()
        notify_provider_onboarding_rejected(app)
        notif = Notification.objects.filter(
            recipient=app.applicant,
            type=NotificationType.ONBOARDING_REJECTED,
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn("Fraudulent documents", notif.body)

    @patch("apps.notifications.tasks.send_push_notification.delay")
    def test_rejected_notification_includes_resubmit_date(self, _mock):
        from apps.notifications.service import notify_provider_onboarding_rejected

        app = self._rejected_app()
        notify_provider_onboarding_rejected(app)
        notif = Notification.objects.filter(
            recipient=app.applicant,
            type=NotificationType.ONBOARDING_REJECTED,
        ).first()
        self.assertIn("can_resubmit_after", notif.data)

    @patch("apps.notifications.tasks.send_push_notification.delay")
    def test_changes_required_notification_includes_requests(self, _mock):
        from apps.notifications.service import (
            notify_provider_onboarding_changes_required,
        )

        app = self._changes_app()
        notify_provider_onboarding_changes_required(app)
        notif = Notification.objects.filter(
            recipient=app.applicant,
            type=NotificationType.ONBOARDING_CHANGES_REQUIRED,
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn("Clearer photo", notif.body)

    @patch("apps.notifications.tasks.send_push_notification.delay")
    def test_resubmit_available_notification(self, _mock):
        from apps.notifications.service import notify_provider_resubmit_available

        provider = _make_pending_provider()
        notify_provider_resubmit_available(provider)
        notif = Notification.objects.filter(
            recipient=provider,
            type=NotificationType.ONBOARDING_RESUBMIT_AVAILABLE,
        ).first()
        self.assertIsNotNone(notif)


# ═════════════════════════════════════════════════════════════════════════════
# 12. Admin Notification Hooks (save_model fires notifications)
# ═════════════════════════════════════════════════════════════════════════════


class AdminNotificationHookTests(TestCase):
    """Verify that save_model fires the correct notifications on FSM transitions."""

    def setUp(self):
        self.region = make_region()
        self.category = make_category()
        self.staff = make_staff()
        from django.contrib.admin.sites import AdminSite

        from apps.provider.admin import ProviderOnboardingAdmin

        self.admin = ProviderOnboardingAdmin(ProviderOnboarding, AdminSite())

    def _mock_request(self):
        request = MagicMock()
        request.user = self.staff
        return request

    def _under_review_app(self):
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)
        app.move_to_review(self.staff)
        app.refresh_from_db()
        return app

    @patch("apps.notifications.tasks.send_push_notification.delay")
    def test_approve_sends_approved_notification(self, _mock):
        from apps.provider.choices import OnboardingStatus

        app = self._under_review_app()
        app.status = OnboardingStatus.APPROVED
        form = MagicMock()

        self.admin.save_model(self._mock_request(), app, form, change=True)

        notif = Notification.objects.filter(
            recipient=app.applicant,
            type=NotificationType.ONBOARDING_APPROVED,
        ).first()
        self.assertIsNotNone(notif)

    @patch("apps.notifications.tasks.send_push_notification.delay")
    def test_reject_sends_rejected_notification(self, _mock):
        from apps.provider.choices import OnboardingStatus

        app = self._under_review_app()
        app.status = OnboardingStatus.REJECTED
        app.rejection_reason = "Unclear NID."
        form = MagicMock()

        self.admin.save_model(self._mock_request(), app, form, change=True)

        notif = Notification.objects.filter(
            recipient=app.applicant,
            type=NotificationType.ONBOARDING_REJECTED,
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn("Unclear NID", notif.body)


# ═════════════════════════════════════════════════════════════════════════════
# 13. NID number → DOB decode (authoritative, deterministic)
# ═════════════════════════════════════════════════════════════════════════════


class NidDobDecodeTests(SimpleTestCase):
    def test_decodes_2000s_and_1900s(self):
        from datetime import date

        from apps.provider.ai_validation import decode_nid_dob

        self.assertEqual(decode_nid_dob("30307020102112"), date(2003, 7, 2))
        self.assertEqual(decode_nid_dob("29512210101234"), date(1995, 12, 21))

    def test_decodes_from_partial_number_via_leading_digits(self):
        from datetime import date

        from apps.provider.ai_validation import decode_nid_dob

        # Only 11 of 14 digits read — the DOB lives in the leading 7.
        self.assertEqual(decode_nid_dob("30307021213"), date(2003, 7, 2))
        self.assertEqual(decode_nid_dob("3030702"), date(2003, 7, 2))

    def test_decodes_arabic_indic_digits(self):
        from datetime import date

        from apps.provider.ai_validation import decode_nid_dob

        # The model sometimes returns the number in Arabic-Indic numerals.
        self.assertEqual(decode_nid_dob("٣٠٣٠٧٠٢٠١٠٢١١٢"), date(2003, 7, 2))

    def test_rejects_serial_malformed_and_implausible(self):
        from apps.provider.ai_validation import decode_nid_dob

        for bad in (
            "IW8931728",
            "012345",
            "",
            None,
            "abc",
            "01012345678",
            "203070210000",
        ):
            self.assertIsNone(decode_nid_dob(bad))

    def test_enrichment_overwrites_dob_and_age_check(self):
        from apps.provider.ai_validation import _apply_nid_dob_decode

        report = {
            "extracted_data": {
                "nid_number": "30307020102112",
                "dob_on_nid": "21/12/1995",
            },
            "age_check": {"consistent": True, "notes": "model read"},
        }
        _apply_nid_dob_decode(report, form_dob="02/07/2003")
        self.assertEqual(report["extracted_data"]["dob_on_nid"], "02/07/2003")
        self.assertTrue(report["age_check"]["consistent"])

    def test_enrichment_noop_without_valid_number(self):
        from apps.provider.ai_validation import _apply_nid_dob_decode

        report = {
            "extracted_data": {"nid_number": "IW8931728", "dob_on_nid": "21/12/1995"}
        }
        _apply_nid_dob_decode(report, form_dob="02/07/2003")
        self.assertEqual(report["extracted_data"]["dob_on_nid"], "21/12/1995")


# ═════════════════════════════════════════════════════════════════════════════
# 14. AI Validation Fallback Paths
# ═════════════════════════════════════════════════════════════════════════════


class AiValidationFallbackTests(TestCase):
    def setUp(self):
        self.region = make_region()
        self.category = make_category()
        # Patch Constance config so tests never hit Redis and can control flags.
        patcher = patch("apps.provider.ai_validation.config")
        self.mock_config = patcher.start()
        self.mock_config.AI_VALIDATION_ENABLED = True
        # Pin to a single provider so tests are deterministic and fast.
        self.mock_config.AI_VALIDATION_PROVIDER = "anthropic"
        self.addCleanup(patcher.stop)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _mock_provider(report: dict):
        """_PROVIDERS-compatible callable that returns a pre-built report."""
        import json

        raw = json.dumps(report)

        def _fn(system, text, docs):
            return report, raw, 100, 50, 20, "mock-model"

        return _fn

    @staticmethod
    def _failing_provider(exc: Exception):
        """_PROVIDERS-compatible callable that always raises exc."""

        def _fn(system, text, docs):
            raise exc

        return _fn

    # ── tests ─────────────────────────────────────────────────────────────────

    def test_returns_passed_when_flag_disabled(self):
        """Constance flag off → instant passed result, no API call made."""
        self.mock_config.AI_VALIDATION_ENABLED = False
        from apps.provider.ai_validation import validate_onboarding

        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)
        result = validate_onboarding(app)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["overall_confidence"], 1.0)
        self.assertEqual(result["issues"], [])

    @override_settings(ANTHROPIC_API_KEY="")
    def test_returns_flagged_when_no_api_key(self):
        """Missing API key raises ValueError (non-transient) → no retries → flagged."""
        from apps.provider.ai_validation import validate_onboarding

        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)
        result = validate_onboarding(app)
        self.assertEqual(result["status"], "flagged")
        self.assertTrue(len(result["issues"]) > 0)

    def test_returns_flagged_when_no_documents(self):
        """Application with no uploaded files → early fallback before any API call."""
        from apps.provider.ai_validation import validate_onboarding

        provider = _make_pending_provider()
        app = ProviderOnboarding.objects.create(
            applicant=provider,
            first_name=provider.first_name,
            last_name=provider.last_name,
            email=provider.email,
            phone=provider.phone,
            status=OnboardingStatus.DRAFT,
        )
        result = validate_onboarding(app)
        self.assertEqual(result["status"], "flagged")

    def test_returns_flagged_on_api_error(self):
        """Transient error exhausts all 3 attempts → status=flagged."""
        from apps.provider.ai_validation import validate_onboarding

        call_count = {"n": 0}

        def _failing(system, text, docs):
            call_count["n"] += 1
            raise ConnectionError("connection reset")  # transient

        with patch.dict(
            "apps.provider.ai_validation._PROVIDERS", {"anthropic": _failing}
        ):
            with patch("apps.provider.ai_validation.time.sleep"):
                provider = _make_pending_provider()
                app = make_onboarding(self.region, self.category, applicant=provider)
                result = validate_onboarding(app)

        self.assertEqual(result["status"], "flagged")
        self.assertEqual(call_count["n"], 3)

    def test_returns_flagged_on_json_decode_error(self):
        """Non-JSON response raises JSONDecodeError (non-transient) → no retries → flagged."""
        import json

        from apps.provider.ai_validation import validate_onboarding

        def _bad_json(system, text, docs):
            raise json.JSONDecodeError("bad", "", 0)

        with patch.dict(
            "apps.provider.ai_validation._PROVIDERS", {"anthropic": _bad_json}
        ):
            provider = _make_pending_provider()
            app = make_onboarding(self.region, self.category, applicant=provider)
            result = validate_onboarding(app)

        self.assertEqual(result["status"], "flagged")

    def test_derives_passed_status_from_high_confidence(self):
        """High confidence + all valid docs → status=passed."""
        from apps.provider.ai_validation import validate_onboarding

        report = {
            "document_checks": {
                "nid_front": {"valid": True, "notes": ""},
                "nid_back": {"valid": True, "notes": ""},
                "police_clearance": {"valid": True, "notes": ""},
                "professional_cert": {"valid": None, "notes": "not provided"},
            },
            "age_check": {"consistent": True, "notes": "Looks 25+"},
            "issues": [],
            "overall_confidence": 0.95,
        }
        with patch.dict(
            "apps.provider.ai_validation._PROVIDERS",
            {"anthropic": self._mock_provider(report)},
        ):
            provider = _make_pending_provider()
            app = make_onboarding(self.region, self.category, applicant=provider)
            result = validate_onboarding(app)

        self.assertEqual(result["status"], "passed")

    def test_derives_failed_status_from_invalid_doc_and_low_confidence(self):
        """Invalid docs + very low confidence → status=failed."""
        from apps.provider.ai_validation import validate_onboarding

        report = {
            "document_checks": {
                "nid_front": {"valid": False, "notes": "Not an NID"},
                "nid_back": {"valid": False, "notes": "Wrong document"},
                "police_clearance": {"valid": True, "notes": ""},
                "professional_cert": {"valid": None, "notes": "not provided"},
            },
            "age_check": {"consistent": False, "notes": "Age mismatch"},
            "issues": [
                "NID front does not match expected format",
                "Age mismatch on NID",
            ],
            "overall_confidence": 0.2,
        }
        with patch.dict(
            "apps.provider.ai_validation._PROVIDERS",
            {"anthropic": self._mock_provider(report)},
        ):
            provider = _make_pending_provider()
            app = make_onboarding(self.region, self.category, applicant=provider)
            result = validate_onboarding(app)

        self.assertEqual(result["status"], "failed")

    def test_cascade_falls_back_to_next_provider_on_failure(self):
        """'all' mode: first provider fails non-transiently, second provider succeeds."""
        from apps.provider.ai_validation import validate_onboarding

        self.mock_config.AI_VALIDATION_PROVIDER = "all"
        good_report = {
            "document_checks": {
                "nid_front": {"valid": True, "notes": ""},
                "nid_back": {"valid": True, "notes": ""},
                "police_clearance": {"valid": True, "notes": ""},
                "professional_cert": {"valid": None, "notes": "not provided"},
            },
            "age_check": {"consistent": True, "notes": ""},
            "issues": [],
            "overall_confidence": 0.90,
        }

        def _fail_anthropic(system, text, docs):
            raise ValueError("ANTHROPIC_API_KEY not set")

        providers_patch = {
            "anthropic": _fail_anthropic,
            "openai": self._mock_provider(good_report),
            "gemini": self._mock_provider(good_report),
            "groq": self._mock_provider(good_report),
        }
        with patch.dict("apps.provider.ai_validation._PROVIDERS", providers_patch):
            provider = _make_pending_provider()
            app = make_onboarding(self.region, self.category, applicant=provider)
            result = validate_onboarding(app)

        self.assertEqual(result["status"], "passed")

    def test_transient_error_retried_then_succeeds(self):
        """Transient errors trigger retries; success on 3rd attempt → status=passed."""
        from apps.provider.ai_validation import validate_onboarding

        attempts = {"n": 0}
        success_report = {
            "document_checks": {
                k: {"valid": True, "notes": ""}
                for k in (
                    "nid_front",
                    "nid_back",
                    "police_clearance",
                    "professional_cert",
                )
            },
            "age_check": {"consistent": True, "notes": ""},
            "issues": [],
            "overall_confidence": 0.85,
        }

        def _flaky(system, text, docs):
            import json

            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ConnectionError("timeout")
            return success_report, json.dumps(success_report), 100, 10, 10, "mock-model"

        with patch.dict(
            "apps.provider.ai_validation._PROVIDERS", {"anthropic": _flaky}
        ):
            with patch("apps.provider.ai_validation.time.sleep"):
                provider = _make_pending_provider()
                app = make_onboarding(self.region, self.category, applicant=provider)
                result = validate_onboarding(app)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(attempts["n"], 3)


# ═════════════════════════════════════════════════════════════════════════════
# 14. Celery Task
# ═════════════════════════════════════════════════════════════════════════════


class TaskTests(TestCase):
    def setUp(self):
        self.region = make_region()
        self.category = make_category()

    @patch("apps.provider.ai_validation.validate_onboarding")
    def test_task_updates_ai_status_to_passed(self, mock_validate):
        mock_validate.return_value = {
            "status": "passed",
            "issues": [],
            "overall_confidence": 0.95,
            "document_checks": {},
            "age_check": {},
        }
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)

        from apps.provider.tasks import validate_onboarding_documents

        validate_onboarding_documents(str(app.pk))

        app.refresh_from_db()
        self.assertEqual(app.ai_validation_status, AIValidationStatus.PASSED)
        self.assertEqual(app.ai_validation_report["status"], "passed")

    @patch("apps.provider.ai_validation.validate_onboarding")
    def test_task_updates_ai_status_to_flagged(self, mock_validate):
        mock_validate.return_value = {
            "status": "flagged",
            "issues": ["Blurry photo"],
            "overall_confidence": 0.5,
            "document_checks": {},
            "age_check": {},
        }
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)

        from apps.provider.tasks import validate_onboarding_documents

        validate_onboarding_documents(str(app.pk))

        app.refresh_from_db()
        self.assertEqual(app.ai_validation_status, AIValidationStatus.FLAGGED)

    @patch("apps.provider.ai_validation.validate_onboarding")
    def test_task_marks_flagged_after_max_retries(self, mock_validate):
        """If all retries are exhausted, status is set to FLAGGED not left as RUNNING."""
        mock_validate.side_effect = Exception("Network error")
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)

        # Simulate the task with max_retries already exhausted
        # Call _mark_flagged directly (which is what the task calls on final failure)
        from apps.provider.tasks import _mark_flagged

        _mark_flagged(str(app.pk), "AI validation failed after max retries")
        app.refresh_from_db()
        self.assertEqual(app.ai_validation_status, AIValidationStatus.FLAGGED)

    def test_task_handles_missing_onboarding_gracefully(self):
        """Non-existent onboarding ID does not raise — task logs and returns."""
        from apps.provider.tasks import validate_onboarding_documents

        # Should not raise
        validate_onboarding_documents(str(uuid.uuid4()))

    @patch("apps.provider.ai_validation.validate_onboarding")
    def test_task_sets_running_status_before_validation(self, mock_validate):
        """ai_validation_status is set to RUNNING before the API call."""
        statuses_seen = []

        def _side_effect(onboarding):
            app = ProviderOnboarding.objects.get(pk=onboarding.pk)
            statuses_seen.append(app.ai_validation_status)
            return {
                "status": "passed",
                "issues": [],
                "overall_confidence": 0.9,
                "document_checks": {},
                "age_check": {},
            }

        mock_validate.side_effect = _side_effect
        provider = _make_pending_provider()
        app = make_onboarding(self.region, self.category, applicant=provider)

        from apps.provider.tasks import validate_onboarding_documents

        validate_onboarding_documents(str(app.pk))

        self.assertIn(AIValidationStatus.RUNNING, statuses_seen)
