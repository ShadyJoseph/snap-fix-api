"""
End-to-end tests for the AI-powered provider recommendation feature.

Coverage:
  - score_provider()         — unit tests for each signal and edge cases
  - get_top_providers()      — filtering, ranking, radius exclusion
  - generate_recommendation_reasons() — AI pipeline: bypass, success, retry,
                                        cascade fallback, log writing
  - POST /requests/ booking_mode=broadcast  — unchanged behaviour
  - POST /requests/ booking_mode=recommended — inline recommendations in response
  - POST /requests/recommended/              — direct booking without favorites check
  - GET  /requests/open/                     — match_score annotation
  - Provider.decline()                       — declined_jobs tracking
  - AIRecommendationLog                      — immutable audit trail
"""

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.booking.choices import BookingMode, ServiceRequestStatus
from apps.booking.models import AIRecommendationLog, ServiceRequest
from apps.notifications.choices import NotificationType
from apps.notifications.models import Notification
from factories import (
    CAIRO,
    make_category,
    make_customer,
    make_image,
    make_provider,
    make_region,
    make_service_request,
)

TASK_PATH = "apps.notifications.tasks.send_push_notification.delay"

# ── Shared helpers ─────────────────────────────────────────────────────────────


def _provider_near_cairo(**kwargs):
    """Create a verified, available provider located at CAIRO with good stats."""
    active = kwargs.pop("active", True)
    verified = kwargs.pop("verified", True)
    p = make_provider(active=active, verified=verified)
    # Set geo and scoring fields explicitly — create_user doesn't handle them.
    p.location = kwargs.pop("location", CAIRO)
    p.service_radius = kwargs.pop("service_radius", 10)
    p.is_available = kwargs.pop("is_available", True)
    p.average_rating = kwargs.pop("average_rating", Decimal("4.00"))
    p.total_jobs = kwargs.pop("total_jobs", 10)
    p.completed_jobs = kwargs.pop("completed_jobs", 9)
    p.declined_jobs = kwargs.pop("declined_jobs", 0)
    for key, val in kwargs.items():
        setattr(p, key, val)
    p.save()
    return p


def _ai_provider_fn(reasons: dict):
    """Return a _PROVIDERS-compatible callable that yields pre-built reasons."""

    def _fn(system: str, prompt: str) -> str:
        return json.dumps(reasons)

    return _fn


def _failing_ai_provider(exc: Exception):
    """Return a _PROVIDERS-compatible callable that always raises exc."""

    def _fn(system: str, prompt: str) -> str:
        raise exc

    return _fn


def _mock_config(enabled=True, provider_setting="all"):
    """Return a mock that stands in for `constance.config`."""
    cfg = MagicMock()
    cfg.AI_RECOMMENDATION_ENABLED = enabled
    cfg.AI_RECOMMENDATION_PROVIDER = provider_setting
    return cfg


# ── Score provider: unit tests ─────────────────────────────────────────────────


class ScoreProviderTests(TestCase):
    def setUp(self):
        from apps.booking.recommendation import score_provider

        self.score = score_provider
        self.provider = _provider_near_cairo()

    def test_perfect_score_when_all_signals_max(self):
        self.provider.average_rating = Decimal("5.00")
        self.provider.total_jobs = 10
        self.provider.completed_jobs = 10
        self.provider.service_radius = 10
        result = self.score(
            self.provider, distance_km=0, is_urgent=True, is_favorite=True
        )
        self.assertEqual(result["score"], 100.0)

    def test_score_zero_distance_gives_max_distance_signal(self):
        result = self.score(
            self.provider, distance_km=0, is_urgent=False, is_favorite=False
        )
        self.assertEqual(result["signals"]["distance"], 100.0)

    def test_score_at_radius_boundary_gives_zero_distance_signal(self):
        self.provider.service_radius = 10
        result = self.score(
            self.provider, distance_km=10, is_urgent=False, is_favorite=False
        )
        self.assertEqual(result["signals"]["distance"], 0.0)

    def test_distance_beyond_radius_clamped_to_zero(self):
        self.provider.service_radius = 10
        result = self.score(
            self.provider, distance_km=15, is_urgent=False, is_favorite=False
        )
        self.assertEqual(result["signals"]["distance"], 0.0)

    def test_favourite_adds_15_points_to_score(self):
        r_no_fav = self.score(self.provider, 0, False, is_favorite=False)
        r_fav = self.score(self.provider, 0, False, is_favorite=True)
        self.assertAlmostEqual(r_fav["score"] - r_no_fav["score"], 15.0, places=1)

    def test_unavailable_provider_gets_zero_urgency_signal(self):
        self.provider.is_available = False
        result = self.score(self.provider, 0, is_urgent=True, is_favorite=False)
        self.assertEqual(result["signals"]["urgency_availability"], 0.0)

    def test_available_non_urgent_gets_50_urgency_signal(self):
        self.provider.is_available = True
        result = self.score(self.provider, 0, is_urgent=False, is_favorite=False)
        self.assertEqual(result["signals"]["urgency_availability"], 50.0)

    def test_available_urgent_gets_100_urgency_signal(self):
        self.provider.is_available = True
        result = self.score(self.provider, 0, is_urgent=True, is_favorite=False)
        self.assertEqual(result["signals"]["urgency_availability"], 100.0)

    def test_new_provider_with_no_jobs_gets_50_completion_signal(self):
        self.provider.total_jobs = 0
        self.provider.completed_jobs = 0
        result = self.score(self.provider, 0, False, False)
        self.assertEqual(result["signals"]["completion_rate"], 50.0)

    def test_five_star_rating_gives_100_rating_signal(self):
        self.provider.average_rating = Decimal("5.00")
        result = self.score(self.provider, 0, False, False)
        self.assertEqual(result["signals"]["rating"], 100.0)

    def test_zero_star_rating_gives_zero_rating_signal(self):
        self.provider.average_rating = Decimal("0.00")
        result = self.score(self.provider, 0, False, False)
        self.assertEqual(result["signals"]["rating"], 0.0)

    def test_score_is_between_0_and_100(self):
        result = self.score(self.provider, 5, True, True)
        self.assertGreaterEqual(result["score"], 0.0)
        self.assertLessEqual(result["score"], 100.0)

    def test_returned_dict_has_required_keys(self):
        result = self.score(self.provider, 0, False, False)
        self.assertIn("score", result)
        self.assertIn("signals", result)
        for key in (
            "rating",
            "distance",
            "completion_rate",
            "is_favorite",
            "urgency_availability",
        ):
            self.assertIn(key, result["signals"])


# ── Get top providers: filtering and ranking ───────────────────────────────────


class GetTopProvidersTests(TestCase):
    def setUp(self):
        from apps.booking.recommendation import get_top_providers

        self.get_top = get_top_providers
        self.category = make_category()
        self.region = make_region()
        self.customer = make_customer()
        self.location = CAIRO

    def _make_nearby_provider(self, **kwargs):
        p = _provider_near_cairo(**kwargs)
        p.categories.add(self.category)
        return p

    def test_returns_at_most_3_by_default(self):
        for _ in range(5):
            self._make_nearby_provider()
        results = self.get_top(self.category, self.location, False, self.customer)
        self.assertLessEqual(len(results), 3)

    def test_returns_empty_when_no_providers(self):
        results = self.get_top(self.category, self.location, False, self.customer)
        self.assertEqual(results, [])

    def test_excludes_unverified_providers(self):
        p = self._make_nearby_provider(verified=False)
        results = self.get_top(self.category, self.location, False, self.customer)
        ids = [r["provider"].pk for r in results]
        self.assertNotIn(p.pk, ids)

    def test_excludes_inactive_providers(self):
        p = self._make_nearby_provider(active=False)
        results = self.get_top(self.category, self.location, False, self.customer)
        ids = [r["provider"].pk for r in results]
        self.assertNotIn(p.pk, ids)

    def test_excludes_unavailable_providers(self):
        p = self._make_nearby_provider(is_available=False)
        results = self.get_top(self.category, self.location, False, self.customer)
        ids = [r["provider"].pk for r in results]
        self.assertNotIn(p.pk, ids)

    def test_excludes_providers_who_dont_offer_category(self):
        p = _provider_near_cairo()  # no category added
        results = self.get_top(self.category, self.location, False, self.customer)
        ids = [r["provider"].pk for r in results]
        self.assertNotIn(p.pk, ids)

    def test_excludes_providers_beyond_service_radius(self):
        far_point = Point(34.0, 32.0, srid=4326)  # ~hundreds of km from Cairo
        p = _provider_near_cairo(location=far_point, service_radius=5)
        p.categories.add(self.category)
        results = self.get_top(self.category, self.location, False, self.customer)
        ids = [r["provider"].pk for r in results]
        self.assertNotIn(p.pk, ids)

    def test_results_sorted_by_score_descending(self):
        # High-rated provider
        p_high = self._make_nearby_provider(
            average_rating=Decimal("5.00"), total_jobs=20, completed_jobs=20
        )
        # Low-rated provider
        self._make_nearby_provider(
            average_rating=Decimal("1.00"), total_jobs=20, completed_jobs=0
        )
        results = self.get_top(self.category, self.location, False, self.customer)
        if len(results) >= 2:
            self.assertGreaterEqual(results[0]["score"], results[1]["score"])
        self.assertEqual(results[0]["provider"].pk, p_high.pk)

    def test_favourite_provider_scores_higher(self):
        p_fav = self._make_nearby_provider(average_rating=Decimal("4.00"))
        p_non_fav = self._make_nearby_provider(average_rating=Decimal("4.00"))
        self.customer.favorite_providers.add(p_fav)
        results = self.get_top(
            self.category, self.location, False, self.customer, limit=2
        )
        fav_result = next(r for r in results if r["provider"].pk == p_fav.pk)
        non_fav_result = next(r for r in results if r["provider"].pk == p_non_fav.pk)
        self.assertGreater(fav_result["score"], non_fav_result["score"])

    def test_result_dict_has_expected_keys(self):
        self._make_nearby_provider()
        results = self.get_top(self.category, self.location, False, self.customer)
        self.assertEqual(len(results), 1)
        item = results[0]
        for key in ("provider", "distance_km", "is_favorite", "score", "signals"):
            self.assertIn(key, item)

    def test_is_favourite_true_when_in_favorites(self):
        p = self._make_nearby_provider()
        self.customer.favorite_providers.add(p)
        results = self.get_top(self.category, self.location, False, self.customer)
        self.assertTrue(results[0]["is_favorite"])

    def test_is_favourite_false_when_not_in_favorites(self):
        self._make_nearby_provider()
        results = self.get_top(self.category, self.location, False, self.customer)
        self.assertFalse(results[0]["is_favorite"])

    def test_custom_limit_respected(self):
        for _ in range(5):
            self._make_nearby_provider()
        results = self.get_top(
            self.category, self.location, False, self.customer, limit=2
        )
        self.assertLessEqual(len(results), 2)


# ── AI recommendation: unit tests ─────────────────────────────────────────────


class GenerateRecommendationReasonsTests(TestCase):
    def setUp(self):
        self.category = make_category()
        self.region = make_region()
        self.customer = make_customer()
        self.provider = _provider_near_cairo()
        self.provider.categories.add(self.category)

        from apps.booking.recommendation import score_provider

        dist = 0.5
        scored = score_provider(self.provider, dist, False, False)
        self.scored_providers = [
            {
                "provider": self.provider,
                "distance_km": dist,
                "is_favorite": False,
                **scored,
            }
        ]

        # Patch Constance so tests never touch Redis.
        patcher = patch("apps.booking.ai_recommendation.config")
        self.mock_cfg = patcher.start()
        self.mock_cfg.AI_RECOMMENDATION_ENABLED = True
        self.mock_cfg.AI_RECOMMENDATION_PROVIDER = "openai"
        self.addCleanup(patcher.stop)

    def _call(self, **kwargs):
        from apps.booking.ai_recommendation import generate_recommendation_reasons

        return generate_recommendation_reasons(
            scored_providers=self.scored_providers,
            category_name=self.category.name,
            is_urgent=False,
            **kwargs,
        )

    # ── Feature flag off ──────────────────────────────────────

    def test_flag_disabled_returns_generic_reasons_without_ai_call(self):
        self.mock_cfg.AI_RECOMMENDATION_ENABLED = False
        with patch.dict(
            "apps.booking.ai_recommendation._PROVIDERS",
            {"openai": _failing_ai_provider(AssertionError("should not be called"))},
        ):
            result = self._call()
        self.assertIn(str(self.provider.pk), result)
        self.assertIsInstance(result[str(self.provider.pk)], str)

    def test_flag_disabled_writes_bypassed_log(self):
        self.mock_cfg.AI_RECOMMENDATION_ENABLED = False
        self._call()
        log = AIRecommendationLog.objects.latest("triggered_at")
        self.assertEqual(log.outcome, "bypassed")

    # ── Happy path ────────────────────────────────────────────

    def test_success_returns_ai_generated_reasons(self):
        reason = "Great provider near you."
        providers_patch = {"openai": _ai_provider_fn({str(self.provider.pk): reason})}
        with patch.dict("apps.booking.ai_recommendation._PROVIDERS", providers_patch):
            result = self._call()
        self.assertEqual(result[str(self.provider.pk)], reason)

    def test_success_writes_log_with_success_outcome(self):
        reason = "Top-rated."
        providers_patch = {"openai": _ai_provider_fn({str(self.provider.pk): reason})}
        with patch.dict("apps.booking.ai_recommendation._PROVIDERS", providers_patch):
            self._call()
        log = AIRecommendationLog.objects.latest("triggered_at")
        self.assertEqual(log.outcome, "success")

    def test_success_log_captures_candidate_snapshot(self):
        providers_patch = {"openai": _ai_provider_fn({str(self.provider.pk): "ok"})}
        with patch.dict("apps.booking.ai_recommendation._PROVIDERS", providers_patch):
            self._call()
        log = AIRecommendationLog.objects.latest("triggered_at")
        self.assertTrue(len(log.candidate_snapshot) > 0)
        self.assertEqual(
            log.candidate_snapshot[0]["provider_id"], str(self.provider.pk)
        )

    def test_success_log_linked_to_service_request(self):
        sr = make_service_request(self.customer, self.category, self.region)
        providers_patch = {"openai": _ai_provider_fn({str(self.provider.pk): "ok"})}
        with patch.dict("apps.booking.ai_recommendation._PROVIDERS", providers_patch):
            self._call(service_request=sr)
        log = AIRecommendationLog.objects.latest("triggered_at")
        self.assertEqual(log.service_request_id, sr.pk)

    def test_missing_key_in_ai_response_filled_with_generic_reason(self):
        # AI returns an empty dict — missing provider key.
        providers_patch = {"openai": _ai_provider_fn({})}
        with patch.dict("apps.booking.ai_recommendation._PROVIDERS", providers_patch):
            result = self._call()
        key = str(self.provider.pk)
        self.assertIn(key, result)
        self.assertIsInstance(result[key], str)
        self.assertTrue(len(result[key]) > 0)

    # ── Transient errors & retries ────────────────────────────

    def test_transient_error_retries_3_times_before_next_provider(self):
        call_count = {"n": 0}

        def _transient(system, prompt):
            call_count["n"] += 1
            raise ConnectionError("connection reset")

        self.mock_cfg.AI_RECOMMENDATION_PROVIDER = "openai"
        with patch.dict(
            "apps.booking.ai_recommendation._PROVIDERS", {"openai": _transient}
        ):
            with patch("apps.booking.ai_recommendation.time.sleep"):
                result = self._call()
        # 3 attempts on the single configured provider
        self.assertEqual(call_count["n"], 3)
        # Still returns something (fallback generic reason)
        self.assertIn(str(self.provider.pk), result)

    def test_non_transient_error_breaks_immediately(self):
        call_count = {"n": 0}

        def _non_transient(system, prompt):
            call_count["n"] += 1
            raise ValueError("OPENAI_API_KEY not set")  # non-transient

        self.mock_cfg.AI_RECOMMENDATION_PROVIDER = "openai"
        with patch.dict(
            "apps.booking.ai_recommendation._PROVIDERS", {"openai": _non_transient}
        ):
            self._call()
        # Non-transient: only 1 attempt, no retries
        self.assertEqual(call_count["n"], 1)

    # ── Cascade fallback ──────────────────────────────────────

    def test_cascade_falls_back_to_next_provider_on_non_transient_failure(self):
        reason = "Fallback provider worked."
        self.mock_cfg.AI_RECOMMENDATION_PROVIDER = "all"

        def _fail_openai(system, prompt):
            raise ValueError("OPENAI_API_KEY not set")

        providers_patch = {
            "openai": _fail_openai,
            "gemini": _ai_provider_fn({str(self.provider.pk): reason}),
            "groq": _failing_ai_provider(AssertionError("should not reach groq")),
            "anthropic": _failing_ai_provider(
                AssertionError("should not reach anthropic")
            ),
        }
        with patch.dict("apps.booking.ai_recommendation._PROVIDERS", providers_patch):
            result = self._call()
        self.assertEqual(result[str(self.provider.pk)], reason)

    def test_all_providers_fail_returns_generic_fallback(self):
        self.mock_cfg.AI_RECOMMENDATION_PROVIDER = "all"
        providers_patch = {
            name: _failing_ai_provider(ValueError("key not set"))
            for name in ("openai", "gemini", "groq", "anthropic")
        }
        with patch.dict("apps.booking.ai_recommendation._PROVIDERS", providers_patch):
            result = self._call()
        key = str(self.provider.pk)
        self.assertIn(key, result)
        self.assertIsInstance(result[key], str)

    def test_all_providers_fail_writes_fallback_log(self):
        self.mock_cfg.AI_RECOMMENDATION_PROVIDER = "all"
        providers_patch = {
            name: _failing_ai_provider(ValueError("key not set"))
            for name in ("openai", "gemini", "groq", "anthropic")
        }
        with patch.dict("apps.booking.ai_recommendation._PROVIDERS", providers_patch):
            self._call()
        log = AIRecommendationLog.objects.latest("triggered_at")
        self.assertEqual(log.outcome, "fallback")

    def test_empty_providers_list_returns_empty_dict(self):
        from apps.booking.ai_recommendation import generate_recommendation_reasons

        result = generate_recommendation_reasons([], self.category.name, False)
        self.assertEqual(result, {})


# ── _generic_reasons: rule-based fallback unit tests ──────────────────────────


class GenericReasonsTests(TestCase):
    """
    _generic_reasons() must produce a meaningful, signal-driven sentence for
    every provider — no AI call involved.  These tests cover all branches of
    the scoring thresholds so we know the fallback is correct independently of
    the AI pipeline.
    """

    def setUp(self):
        self.region = make_region()
        self.category = make_category()

    def _item(self, provider, dist_km=1.0, is_favorite=False, is_urgent=False):
        from apps.booking.recommendation import score_provider

        scored = score_provider(provider, dist_km, is_urgent, is_favorite)
        return {
            "provider": provider,
            "distance_km": dist_km,
            "is_favorite": is_favorite,
            **scored,
        }

    def _call(self, items):
        from apps.booking.ai_recommendation import _generic_reasons

        return _generic_reasons(items)

    def test_returns_string_for_every_provider(self):
        p = _provider_near_cairo()
        result = self._call([self._item(p)])
        self.assertIn(str(p.pk), result)
        self.assertIsInstance(result[str(p.pk)], str)
        self.assertGreater(len(result[str(p.pk)]), 0)

    def test_reason_ends_with_period_and_starts_uppercase(self):
        p = _provider_near_cairo()
        reason = self._call([self._item(p)])[str(p.pk)]
        self.assertTrue(reason.endswith("."))
        self.assertTrue(reason[0].isupper())

    def test_favorite_mentioned_when_is_favorite_true(self):
        p = _provider_near_cairo()
        reason = self._call([self._item(p, is_favorite=True)])[str(p.pk)]
        self.assertIn("favorites", reason)

    def test_favorite_not_mentioned_when_is_favorite_false(self):
        p = _provider_near_cairo()
        reason = self._call([self._item(p, is_favorite=False)])[str(p.pk)]
        self.assertNotIn("favorites", reason)

    def test_high_rating_highlighted(self):
        # average_rating=5 → rating signal=100 ≥ 70 → "highly rated"
        p = _provider_near_cairo(average_rating=5)
        reason = self._call([self._item(p)])[str(p.pk)]
        self.assertIn("highly rated", reason.lower())

    def test_low_rating_shown_plainly(self):
        # average_rating=2 → rating signal=40 < 70 → plain "rated X★"
        p = _provider_near_cairo(average_rating=2)
        reason = self._call([self._item(p)])[str(p.pk)]
        self.assertIn("rated", reason.lower())
        self.assertNotIn("highly rated", reason.lower())

    def test_very_close_provider_shows_distance(self):
        # service_radius=10, dist=0.5 → distance signal=95 ≥ 70 → "very close"
        p = _provider_near_cairo(service_radius=10)
        reason = self._call([self._item(p, dist_km=0.5)])[str(p.pk)]
        self.assertIn("very close", reason)

    def test_medium_distance_shows_km_figure(self):
        # service_radius=20, dist=8 → distance signal=60 → ≥30 → "X km away"
        p = _provider_near_cairo(service_radius=20)
        reason = self._call([self._item(p, dist_km=8)])[str(p.pk)]
        self.assertIn("km away", reason)

    def test_high_completion_rate_highlighted(self):
        p = _provider_near_cairo(total_jobs=10, completed_jobs=9)
        reason = self._call([self._item(p)])[str(p.pk)]
        self.assertIn("completion rate", reason)

    def test_new_provider_zero_jobs_no_completion_mention(self):
        p = make_provider(active=True, verified=True)
        p.categories.add(self.category)
        reason = self._call([self._item(p)])[str(p.pk)]
        self.assertNotIn("completion rate", reason)

    def test_available_now_shown_for_urgent_available_provider(self):
        p = _provider_near_cairo(is_available=True)
        reason = self._call([self._item(p, is_urgent=True)])[str(p.pk)]
        self.assertIn("available now", reason)

    def test_available_now_not_shown_for_non_urgent(self):
        p = _provider_near_cairo(is_available=True)
        reason = self._call([self._item(p, is_urgent=False)])[str(p.pk)]
        self.assertNotIn("available now", reason)

    def test_multiple_providers_all_get_reasons(self):
        p1 = _provider_near_cairo()
        p2 = _provider_near_cairo()
        items = [self._item(p1), self._item(p2)]
        result = self._call(items)
        self.assertIn(str(p1.pk), result)
        self.assertIn(str(p2.pk), result)


# ── Base test case for view tests ──────────────────────────────────────────────


class RecommendationTestCase(APITestCase):
    def setUp(self):
        self.customer = make_customer()
        self.provider = _provider_near_cairo()
        self.category = make_category()
        self.region = make_region()
        self.provider.categories.add(self.category)

    def authenticate_customer(self):
        self.client.force_authenticate(user=self.customer)

    def authenticate_provider(self):
        self.client.force_authenticate(user=self.provider)

    def _base_payload(self, **overrides):
        payload = {
            "category": self.category.id,
            "region": self.region.id,
            "address": "123 Test St",
            "floor_number": "3",
            "apartment_number": "12",
            "special_mark": "Blue door",
            "latitude": 30.0444,
            "longitude": 31.2357,
            "title": "Fix leaking pipe",
            "description": "Pipe under sink is leaking",
            "preferred_date": "2026-08-01",
            "preferred_time": "10:00:00",
        }
        payload.update(overrides)
        return payload

    def _post_create(self, **overrides):
        url = reverse("bookings:request-list-create")
        return self.client.post(
            url, {**self._base_payload(**overrides), "photos": make_image()}
        )


# ── Broadcast mode: existing behaviour unchanged ───────────────────────────────


class BroadcastBookingModeTests(RecommendationTestCase):
    """Broadcast is the default. No recommendations key in response."""

    def test_default_mode_is_broadcast(self):
        self.authenticate_customer()
        response = self._post_create()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        sr = ServiceRequest.objects.get(pk=response.data["id"])
        self.assertEqual(sr.booking_mode, BookingMode.BROADCAST)

    def test_explicit_broadcast_has_no_recommendations_key(self):
        self.authenticate_customer()
        response = self._post_create(booking_mode="broadcast")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("recommendations", response.data)

    def test_broadcast_request_status_is_pending(self):
        self.authenticate_customer()
        response = self._post_create(booking_mode="broadcast")
        self.assertEqual(response.data["status"], ServiceRequestStatus.PENDING)

    def test_broadcast_request_enters_open_pool(self):
        self.authenticate_customer()
        self._post_create(booking_mode="broadcast")
        self.assertEqual(
            ServiceRequest.objects.filter(status=ServiceRequestStatus.PENDING).count(),
            1,
        )


# ── Recommended mode: create request with inline recommendations ───────────────


class RecommendedModeCreateTests(RecommendationTestCase):
    """
    POST /requests/ with booking_mode=recommended returns the created request
    plus a 'recommendations' list of scored providers with AI reasons.
    """

    def _post_recommended(self, **overrides):
        with patch(
            "apps.booking.views._build_recommendations",
            return_value=[
                {
                    "id": str(self.provider.pk),
                    "full_name": self.provider.get_full_name(),
                    "business_name": "",
                    "average_rating": "4.00",
                    "total_reviews": 0,
                    "completed_jobs": 9,
                    "hourly_rate": None,
                    "years_of_experience": 0,
                    "acceptance_rate": None,
                    "distance_km": 0.0,
                    "is_favorite": False,
                    "score": 72.0,
                    "signals": {},
                    "reason": "Great provider nearby.",
                }
            ],
        ):
            return self._post_create(booking_mode="recommended", **overrides)

    def test_response_contains_recommendations_key(self):
        self.authenticate_customer()
        response = self._post_recommended()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("recommendations", response.data)

    def test_recommendations_is_a_list(self):
        self.authenticate_customer()
        response = self._post_recommended()
        self.assertIsInstance(response.data["recommendations"], list)

    def test_booking_mode_stored_as_recommended(self):
        self.authenticate_customer()
        response = self._post_recommended()
        sr = ServiceRequest.objects.get(pk=response.data["id"])
        self.assertEqual(sr.booking_mode, BookingMode.RECOMMENDED)

    def test_request_status_is_pending_after_create(self):
        self.authenticate_customer()
        response = self._post_recommended()
        self.assertEqual(response.data["status"], ServiceRequestStatus.PENDING)

    def test_no_candidates_returns_empty_recommendations(self):
        self.authenticate_customer()
        # Point far away so no provider qualifies
        with patch(
            "apps.booking.views._build_recommendations",
            return_value=[],
        ):
            response = self._post_create(booking_mode="recommended")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["recommendations"], [])


class RecommendedModeIntegrationTests(RecommendationTestCase):
    """Integration-level: real scoring + AI bypassed via Constance flag."""

    def setUp(self):
        super().setUp()
        # Patch Constance so tests never touch Redis.
        patcher = patch("apps.booking.ai_recommendation.config")
        self.mock_cfg = patcher.start()
        self.mock_cfg.AI_RECOMMENDATION_ENABLED = False  # bypass AI, generic reasons
        self.mock_cfg.AI_RECOMMENDATION_PROVIDER = "all"
        self.addCleanup(patcher.stop)

    def test_recommendations_contain_required_fields(self):
        self.authenticate_customer()
        response = self._post_create(booking_mode="recommended")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        recs = response.data.get("recommendations", [])
        if recs:
            item = recs[0]
            for field in (
                "id",
                "full_name",
                "score",
                "signals",
                "reason",
                "distance_km",
                "is_favorite",
            ):
                self.assertIn(field, item, f"Missing field: {field}")

    def test_recommendation_scores_are_between_0_and_100(self):
        self.authenticate_customer()
        response = self._post_create(booking_mode="recommended")
        recs = response.data.get("recommendations", [])
        for item in recs:
            self.assertGreaterEqual(float(item["score"]), 0)
            self.assertLessEqual(float(item["score"]), 100)

    def test_ai_disabled_still_returns_recommendations_with_generic_reason(self):
        self.authenticate_customer()
        response = self._post_create(booking_mode="recommended")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        recs = response.data.get("recommendations", [])
        if recs:
            # Generic reason contains rating info
            self.assertIsInstance(recs[0]["reason"], str)
            self.assertGreater(len(recs[0]["reason"]), 0)

    def test_favourite_provider_marked_in_recommendations(self):
        self.customer.favorite_providers.add(self.provider)
        self.authenticate_customer()
        response = self._post_create(booking_mode="recommended")
        recs = response.data.get("recommendations", [])
        favourite_rec = next(
            (r for r in recs if str(r["id"]) == str(self.provider.pk)), None
        )
        if favourite_rec:
            self.assertTrue(favourite_rec["is_favorite"])

    def test_log_written_after_recommended_create(self):
        before = AIRecommendationLog.objects.count()
        self.authenticate_customer()
        response = self._post_create(booking_mode="recommended")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        recs = response.data.get("recommendations", [])
        if recs:  # only written when there are candidates
            self.assertGreater(AIRecommendationLog.objects.count(), before)


# ── POST /requests/recommended/ ───────────────────────────────────────────────


class RecommendedBookingViewTests(RecommendationTestCase):
    """
    Tests for the new recommended booking endpoint.

    Key difference from /requests/direct/:
      - Provider does NOT need to be in customer's favorites.
      - booking_mode is stored as 'recommended'.
    """

    url = reverse("bookings:request-recommended")

    def _valid_payload(self, **overrides):
        payload = self._base_payload()
        payload["provider_id"] = str(self.provider.id)
        payload.update(overrides)  # overrides (including provider_id) win
        return payload

    def _post_with_photo(self, **overrides):
        return self.client.post(
            self.url, {**self._valid_payload(**overrides), "photos": make_image()}
        )

    # ── Happy path ────────────────────────────────────────────

    @patch(TASK_PATH)
    def test_create_success_returns_201(self, _):
        self.authenticate_customer()
        response = self._post_with_photo()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch(TASK_PATH)
    def test_request_status_is_assigned(self, _):
        self.authenticate_customer()
        response = self._post_with_photo()
        self.assertEqual(response.data["status"], ServiceRequestStatus.ASSIGNED)

    @patch(TASK_PATH)
    def test_booking_mode_stored_as_recommended(self, _):
        self.authenticate_customer()
        response = self._post_with_photo()
        sr = ServiceRequest.objects.get(pk=response.data["id"])
        self.assertEqual(sr.booking_mode, BookingMode.RECOMMENDED)

    @patch(TASK_PATH)
    def test_correct_provider_assigned(self, _):
        self.authenticate_customer()
        response = self._post_with_photo()
        sr = ServiceRequest.objects.get(pk=response.data["id"])
        self.assertEqual(sr.provider_id, self.provider.pk)

    @patch(TASK_PATH)
    def test_photo_stored(self, _):
        self.authenticate_customer()
        response = self._post_with_photo()
        sr = ServiceRequest.objects.get(pk=response.data["id"])
        self.assertEqual(sr.photos.count(), 1)

    @patch(TASK_PATH)
    def test_increments_provider_total_jobs(self, _):
        self.authenticate_customer()
        before = self.provider.total_jobs
        self._post_with_photo()
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.total_jobs, before + 1)

    @patch(TASK_PATH)
    def test_provider_not_in_favorites_still_succeeds(self, _):
        """Core feature: no favorites check for AI-recommended bookings."""
        # Ensure provider is NOT in favorites
        self.customer.favorite_providers.remove(self.provider)
        self.authenticate_customer()
        response = self._post_with_photo()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch(TASK_PATH)
    def test_fires_direct_booking_notification_to_provider(self, _):
        self.authenticate_customer()
        response = self._post_with_photo()
        sr_id = str(response.data["id"])
        notif = Notification.objects.get(
            recipient=self.provider,
            type=NotificationType.DIRECT_BOOKING_REQUEST,
        )
        self.assertEqual(notif.data["service_request_id"], sr_id)

    # ── Validation failures ───────────────────────────────────

    def test_unauthenticated_returns_401(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_provider_token_returns_403(self):
        self.authenticate_provider()
        response = self._post_with_photo()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_provider_id_returns_400(self):
        self.authenticate_customer()
        payload = self._valid_payload()
        del payload["provider_id"]
        response = self.client.post(self.url, {**payload, "photos": make_image()})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("provider_id", response.data)

    def test_nonexistent_provider_returns_400(self):
        import uuid

        self.authenticate_customer()
        response = self.client.post(
            self.url,
            {
                **self._valid_payload(provider_id=str(uuid.uuid4())),
                "photos": make_image(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch(TASK_PATH)
    def test_unverified_provider_returns_400(self, _):
        unverified = make_provider(verified=False)
        unverified.categories.add(self.category)
        self.authenticate_customer()
        response = self.client.post(
            self.url,
            {
                **self._valid_payload(provider_id=str(unverified.id)),
                "photos": make_image(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("provider_id", response.data)

    @patch(TASK_PATH)
    def test_provider_wrong_category_returns_400(self, _):
        other_category = make_category(name="Electrical", slug="electrical")
        p = _provider_near_cairo()
        p.categories.add(other_category)  # different category
        self.authenticate_customer()
        response = self.client.post(
            self.url,
            {**self._valid_payload(provider_id=str(p.id)), "photos": make_image()},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch(TASK_PATH)
    def test_unavailable_provider_returns_400(self, _):
        self.provider.is_available = False
        self.provider.save(update_fields=["is_available"])
        self.authenticate_customer()
        response = self._post_with_photo()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("provider_id", response.data)

    @patch(TASK_PATH)
    def test_provider_with_active_job_returns_400(self, _):
        # Put provider on an active job so they are "busy"
        other_customer = make_customer()
        active_sr = make_service_request(other_customer, self.category, self.region)
        active_sr.status = ServiceRequestStatus.IN_PROGRESS
        active_sr.provider = self.provider
        active_sr.save(update_fields=["status", "provider"])
        self.authenticate_customer()
        response = self._post_with_photo()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_photo_returns_400(self):
        self.authenticate_customer()
        response = self.client.post(self.url, self._valid_payload())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("photos", response.data)

    # ── Full lifecycle ────────────────────────────────────────

    @patch(TASK_PATH)
    def test_lifecycle_provider_declines_increments_declined_jobs(self, _):
        """After a recommended booking, provider decline → declined_jobs++."""
        self.authenticate_customer()
        sr_id = self._post_with_photo().data["id"]

        self.authenticate_provider()
        self.client.post(
            reverse("bookings:request-decline", args=[sr_id]), {"reason": "Busy"}
        )
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.declined_jobs, 1)

    @patch(TASK_PATH)
    def test_lifecycle_full_quote_start_complete(self, _):
        """Recommended booking → quote → approve → start → complete."""
        self.authenticate_customer()
        sr_id = self._post_with_photo().data["id"]
        self.assertEqual(
            ServiceRequest.objects.get(pk=sr_id).status, ServiceRequestStatus.ASSIGNED
        )

        self.authenticate_provider()
        resp = self.client.post(
            reverse("bookings:request-quote", args=[sr_id]), {"price": "200.00"}
        )
        self.assertEqual(resp.data["status"], ServiceRequestStatus.QUOTED)

        self.authenticate_customer()
        resp = self.client.post(reverse("bookings:request-approve-quote", args=[sr_id]))
        self.assertEqual(resp.data["status"], ServiceRequestStatus.CONFIRMED)

        self.authenticate_provider()
        self.client.post(reverse("bookings:request-start", args=[sr_id]))
        resp = self.client.post(reverse("bookings:request-complete", args=[sr_id]))
        self.assertEqual(resp.data["status"], ServiceRequestStatus.COMPLETED)


# ── Provider open requests: match_score annotation ────────────────────────────


class ProviderOpenRequestsMatchScoreTests(RecommendationTestCase):
    url = reverse("bookings:request-open-pool")

    def setUp(self):
        super().setUp()
        self.sr = make_service_request(self.customer, self.category, self.region)

    def test_match_score_present_in_response(self):
        self.authenticate_provider()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        if results:
            self.assertIn("match_score", results[0])

    def test_match_signals_present_in_response(self):
        self.authenticate_provider()
        response = self.client.get(self.url)
        results = response.data.get("results", response.data)
        if results:
            self.assertIn("match_signals", results[0])

    def test_match_score_between_0_and_100(self):
        self.authenticate_provider()
        response = self.client.get(self.url)
        results = response.data.get("results", response.data)
        for item in results:
            score = item.get("match_score")
            if score is not None:
                self.assertGreaterEqual(float(score), 0)
                self.assertLessEqual(float(score), 100)

    def test_match_score_null_when_provider_has_no_location(self):
        self.provider.location = None
        self.provider.save(update_fields=["location"])
        self.authenticate_provider()
        response = self.client.get(self.url)
        results = response.data.get("results", response.data)
        if results:
            self.assertIsNone(results[0]["match_score"])


# ── Decline tracking ───────────────────────────────────────────────────────────


class DeclineTrackingTests(RecommendationTestCase):
    def setUp(self):
        super().setUp()
        self.sr = make_service_request(self.customer, self.category, self.region)

    def test_decline_increments_declined_jobs(self):
        self.sr.assign(self.provider)
        before = self.provider.declined_jobs
        self.sr.decline(reason="Too far")
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.declined_jobs, before + 1)

    def test_decline_also_decrements_total_jobs(self):
        self.sr.assign(self.provider)
        self.provider.refresh_from_db()  # pick up DB value after F() expression
        before = self.provider.total_jobs
        self.sr.decline()
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.total_jobs, before - 1)

    def test_acceptance_rate_reflects_declines(self):
        # Assign and complete 5 jobs, then decline 1

        self.provider.total_jobs = 5
        self.provider.completed_jobs = 5
        self.provider.declined_jobs = 0
        self.provider.save(
            update_fields=["total_jobs", "completed_jobs", "declined_jobs"]
        )

        self.sr.assign(self.provider)
        self.sr.decline()
        self.provider.refresh_from_db()

        # total_jobs = 5 + 1 (assign) - 1 (decline) = 5; declined_jobs = 1
        # acceptance_rate = (5 - 1) / 5 = 0.8
        self.assertIsNotNone(self.provider.acceptance_rate)
        self.assertAlmostEqual(self.provider.acceptance_rate, 0.8, places=2)

    def test_acceptance_rate_none_for_new_provider(self):
        # make_provider() gives total_jobs=0 (the model default)
        p = make_provider()
        self.assertIsNone(p.acceptance_rate)

    def test_decline_via_api_increments_declined_jobs(self):
        self.sr.assign(self.provider)
        before = self.provider.declined_jobs
        self.client.force_authenticate(user=self.provider)
        with patch(TASK_PATH):
            self.client.post(
                reverse("bookings:request-decline", args=[self.sr.pk]),
                {"reason": "Busy"},
            )
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.declined_jobs, before + 1)


# ── AIRecommendationLog audit trail ───────────────────────────────────────────


class AIRecommendationLogTests(TestCase):
    def setUp(self):
        self.category = make_category()
        self.region = make_region()
        self.customer = make_customer()
        self.provider = _provider_near_cairo()
        self.provider.categories.add(self.category)

        from apps.booking.recommendation import score_provider

        scored = score_provider(self.provider, 0.5, False, False)
        self.scored_providers = [
            {
                "provider": self.provider,
                "distance_km": 0.5,
                "is_favorite": False,
                **scored,
            }
        ]

        patcher = patch("apps.booking.ai_recommendation.config")
        self.mock_cfg = patcher.start()
        self.mock_cfg.AI_RECOMMENDATION_ENABLED = True
        self.mock_cfg.AI_RECOMMENDATION_PROVIDER = "openai"
        self.addCleanup(patcher.stop)

    def _call(self, **kwargs):
        from apps.booking.ai_recommendation import generate_recommendation_reasons

        return generate_recommendation_reasons(
            self.scored_providers, self.category.name, False, **kwargs
        )

    def test_log_written_on_success(self):
        providers_patch = {"openai": _ai_provider_fn({str(self.provider.pk): "great"})}
        with patch.dict("apps.booking.ai_recommendation._PROVIDERS", providers_patch):
            self._call()
        self.assertEqual(
            AIRecommendationLog.objects.filter(outcome="success").count(), 1
        )

    def test_log_written_on_bypass(self):
        self.mock_cfg.AI_RECOMMENDATION_ENABLED = False
        self._call()
        self.assertEqual(
            AIRecommendationLog.objects.filter(outcome="bypassed").count(), 1
        )

    def test_log_written_on_fallback(self):
        self.mock_cfg.AI_RECOMMENDATION_PROVIDER = "all"
        providers_patch = {
            name: _failing_ai_provider(ValueError("no key"))
            for name in ("openai", "gemini", "groq", "anthropic")
        }
        with patch.dict("apps.booking.ai_recommendation._PROVIDERS", providers_patch):
            self._call()
        self.assertEqual(
            AIRecommendationLog.objects.filter(outcome="fallback").count(), 1
        )

    def test_log_captures_category_name(self):
        providers_patch = {"openai": _ai_provider_fn({str(self.provider.pk): "ok"})}
        with patch.dict("apps.booking.ai_recommendation._PROVIDERS", providers_patch):
            self._call()
        log = AIRecommendationLog.objects.latest("triggered_at")
        self.assertEqual(log.category_name, self.category.name)

    def test_log_captures_parsed_reasons(self):
        reason = "Top rated."
        providers_patch = {"openai": _ai_provider_fn({str(self.provider.pk): reason})}
        with patch.dict("apps.booking.ai_recommendation._PROVIDERS", providers_patch):
            self._call()
        log = AIRecommendationLog.objects.latest("triggered_at")
        self.assertEqual(log.parsed_reasons.get(str(self.provider.pk)), reason)

    def test_log_linked_to_service_request_when_provided(self):
        sr = make_service_request(self.customer, self.category, self.region)
        providers_patch = {"openai": _ai_provider_fn({str(self.provider.pk): "ok"})}
        with patch.dict("apps.booking.ai_recommendation._PROVIDERS", providers_patch):
            self._call(service_request=sr)
        log = AIRecommendationLog.objects.latest("triggered_at")
        self.assertEqual(log.service_request_id, sr.pk)

    def test_log_unlinked_when_no_service_request(self):
        providers_patch = {"openai": _ai_provider_fn({str(self.provider.pk): "ok"})}
        with patch.dict("apps.booking.ai_recommendation._PROVIDERS", providers_patch):
            self._call()
        log = AIRecommendationLog.objects.latest("triggered_at")
        self.assertIsNone(log.service_request_id)

    def test_log_records_model_id(self):
        providers_patch = {"openai": _ai_provider_fn({str(self.provider.pk): "ok"})}
        with patch.dict("apps.booking.ai_recommendation._PROVIDERS", providers_patch):
            self._call()
        log = AIRecommendationLog.objects.latest("triggered_at")
        self.assertEqual(log.model_id, "gpt-4o-mini")


# ── _clean_json: robustness tests ─────────────────────────────────────────────


class CleanJsonTests(TestCase):
    def _clean(self, raw):
        from apps.booking.ai_recommendation import _clean_json

        return _clean_json(raw)

    def test_plain_json_passes_through(self):
        result = self._clean('{"1": "reason"}')
        self.assertEqual(result, {"1": "reason"})

    def test_json_code_fence_stripped(self):
        raw = '```json\n{"1": "reason"}\n```'
        self.assertEqual(self._clean(raw), {"1": "reason"})

    def test_plain_code_fence_stripped(self):
        raw = '```\n{"1": "reason"}\n```'
        self.assertEqual(self._clean(raw), {"1": "reason"})

    def test_fence_without_trailing_newline(self):
        raw = '```json{"1": "reason"}```'
        self.assertEqual(self._clean(raw), {"1": "reason"})

    def test_malformed_json_raises_json_decode_error(self):
        import json

        with self.assertRaises(json.JSONDecodeError):
            self._clean("```json\nnot valid json\n```")

    def test_anthropic_prefill_output_parseable(self):
        # Anthropic prefill returns the completion without the opening brace;
        # the adapter prepends "{" before passing to _clean_json.
        raw = '{"1": "reason"}'
        self.assertEqual(self._clean(raw), {"1": "reason"})


# ── Stranded RECOMMENDED request after provider decline ───────────────────────


class RecommendedDeclineBehaviorTests(RecommendationTestCase):
    """
    When a provider declines an AI-recommended booking, the request must
    revert to BROADCAST mode so it can re-enter the open pool — instead of
    being stranded in PENDING but excluded from provider discovery.
    """

    @patch(TASK_PATH)
    def setUp(self, _):
        super().setUp()
        # Create a recommended booking (provider directly assigned).
        url = reverse("bookings:request-recommended")
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(
            url,
            {
                **self._base_payload(),
                "provider_id": str(self.provider.id),
                "photos": make_image(),
            },
        )
        self.sr_id = resp.data["id"]

    @patch(TASK_PATH)
    def test_decline_resets_booking_mode_to_broadcast(self, _):
        self.client.force_authenticate(user=self.provider)
        self.client.post(
            reverse("bookings:request-decline", args=[self.sr_id]),
            {"reason": "Busy"},
        )
        sr = ServiceRequest.objects.get(pk=self.sr_id)
        self.assertEqual(sr.booking_mode, BookingMode.BROADCAST)

    @patch(TASK_PATH)
    def test_decline_makes_request_visible_in_open_pool(self, _):
        self.client.force_authenticate(user=self.provider)
        self.client.post(
            reverse("bookings:request-decline", args=[self.sr_id]),
            {"reason": "Busy"},
        )
        self.client.force_authenticate(user=self.provider)
        response = self.client.get(reverse("bookings:request-open-pool"))
        results = response.data.get("results", response.data)
        ids = [str(r["id"]) for r in results]
        self.assertIn(self.sr_id, ids)


# ── _build_recommendations exception safety ───────────────────────────────────


class BuildRecommendationsExceptionTests(RecommendationTestCase):
    """
    If _build_recommendations raises (e.g. DB error during scoring), the
    ServiceRequest is already committed.  The view must still return 201 with
    recommendations: [] rather than surfacing a 500 to the customer.
    """

    def test_exception_in_build_recommendations_returns_201_with_empty_list(self):
        self.authenticate_customer()
        with patch(
            "apps.booking.views._build_recommendations",
            side_effect=RuntimeError("scoring DB error"),
        ):
            response = self._post_create(booking_mode="recommended")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data.get("recommendations"), [])

    def test_service_request_persisted_even_when_recommendations_fail(self):
        self.authenticate_customer()
        with patch(
            "apps.booking.views._build_recommendations",
            side_effect=RuntimeError("scoring DB error"),
        ):
            response = self._post_create(booking_mode="recommended")
        self.assertTrue(ServiceRequest.objects.filter(pk=response.data["id"]).exists())
