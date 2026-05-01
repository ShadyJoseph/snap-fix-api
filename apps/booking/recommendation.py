"""
Provider recommendation scoring engine.

Shared utility imported by:
  - ServiceRequestListView.create()  (RECOMMENDED booking mode → inline top 3)
  - ProviderOpenRequestsView          (annotates each open request with match_score)

Scoring signals and weights
---------------------------
  rating              30%  — provider's average star rating normalised to 0-100
  distance            25%  — how close the provider is (inverse, capped at service_radius)
  completion_rate     20%  — percentage of assigned jobs the provider completed
  favorite_bonus      15%  — whether this provider is in the customer's favorites
  urgency_avail       10%  — provider is available now (matters more for urgent jobs)
"""

from __future__ import annotations

import logging

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D as GeoDistance

from .utils import haversine_km

# Outer bounding-box applied at DB level before Python radius filtering.
# Providers beyond this threshold are excluded via a spatial index scan,
# keeping the in-memory candidate list small even for large provider tables.
_MAX_SEARCH_RADIUS_KM = 100.0

logger = logging.getLogger(__name__)

_WEIGHTS = {
    "rating": 0.30,
    "distance": 0.25,
    "completion_rate": 0.20,
    "favorite": 0.15,
    "urgency_avail": 0.10,
}


def score_provider(
    provider, distance_km: float, is_urgent: bool, is_favorite: bool
) -> dict:
    """
    Return a breakdown dict with individual signal scores (0-100 each) and a
    final weighted score (0-100).

    Parameters
    ----------
    provider     : Provider instance (needs average_rating, total_jobs,
                   completed_jobs, service_radius, is_available)
    distance_km  : straight-line distance from the service location to the
                   provider's registered location
    is_urgent    : whether the service request is marked urgent
    is_favorite  : whether this provider is in the customer's favourite list
    """
    # ── Rating ────────────────────────────────────────────────
    rating_s = float(provider.average_rating) / 5.0 * 100

    # ── Completion rate ───────────────────────────────────────
    # New providers (0 jobs) get a neutral 50 so they're not penalised unfairly.
    if provider.total_jobs > 0:
        completion_s = provider.get_completion_rate()
    else:
        completion_s = 50.0

    # ── Distance ──────────────────────────────────────────────
    max_dist = float(provider.service_radius) if provider.service_radius else 10.0
    if max_dist <= 0:
        max_dist = 10.0
    distance_s = max(0.0, (1.0 - distance_km / max_dist)) * 100

    # ── Favourite bonus ───────────────────────────────────────
    favorite_s = 100.0 if is_favorite else 0.0

    # ── Urgency availability ──────────────────────────────────
    # Note: an available provider on a non-urgent job scores 50 (not 0), so
    # an unavailable provider carries a hidden 5-point penalty even without
    # urgency.  This is intentional — availability is always a mild positive.
    if provider.is_available:
        urgency_s = 100.0 if is_urgent else 50.0
    else:
        urgency_s = 0.0

    final = (
        rating_s * _WEIGHTS["rating"]
        + distance_s * _WEIGHTS["distance"]
        + completion_s * _WEIGHTS["completion_rate"]
        + favorite_s * _WEIGHTS["favorite"]
        + urgency_s * _WEIGHTS["urgency_avail"]
    )

    return {
        "score": round(final, 2),
        "signals": {
            "rating": round(rating_s, 2),
            "distance": round(distance_s, 2),
            "completion_rate": round(completion_s, 2),
            "is_favorite": is_favorite,
            "urgency_availability": round(urgency_s, 2),
        },
    }


def get_top_providers(
    category,
    location: Point,
    is_urgent: bool,
    customer,
    limit: int = 3,
) -> list[dict]:
    """
    Query, score, and return the top `limit` providers for a service request.

    Each item in the returned list is:
      {
        "provider": <Provider instance>,
        "distance_km": <float>,
        "is_favorite": <bool>,
        "score": <float>,
        "signals": { ... },
      }

    Parameters
    ----------
    category  : Category instance (must match provider.categories)
    location  : Point(lng, lat) of the service address
    is_urgent : urgency flag from the service request
    customer  : Customer instance (used to resolve favourite_providers)
    limit     : how many providers to return (default 3)
    """
    from apps.provider.choices import ProviderVerificationStatus
    from apps.provider.models import Provider

    # Build the base queryset: verified, active, available, offers the category.
    qs = (
        Provider.objects.filter(
            verification_status=ProviderVerificationStatus.VERIFIED,
            is_active=True,
            is_available=True,
            categories=category,
        )
        .select_related("region")
        .prefetch_related("categories")
    )

    # Annotate with geo-distance and apply a coarse bounding-box pre-filter at
    # the DB level (ST_DWithin uses a spatial index).  The precise per-provider
    # service_radius check still runs in Python below.
    if location:
        qs = qs.filter(
            location__dwithin=(location, GeoDistance(km=_MAX_SEARCH_RADIUS_KM))
        ).annotate(geo_distance=Distance("location", location))

    providers = list(qs)
    if not providers:
        return []

    # Resolve customer favorites once (avoids N+1 inside the loop).
    try:
        favorite_ids = set(customer.favorite_providers.values_list("pk", flat=True))
    except Exception:
        logger.exception(
            "get_top_providers: could not load favourite_providers for customer %s",
            customer.pk,
        )
        favorite_ids = set()

    scored = []
    for p in providers:
        # Calculate distance in km.
        if hasattr(p, "geo_distance") and p.geo_distance is not None:
            dist_km = round(p.geo_distance.km, 3)
        elif p.location and location:
            dist_km = haversine_km(location.y, location.x, p.location.y, p.location.x)
        else:
            dist_km = 999.0

        # Skip providers who are outside their own declared service radius.
        radius = p.service_radius or 10
        if dist_km > radius:
            continue

        is_fav = p.pk in favorite_ids
        result = score_provider(p, dist_km, is_urgent, is_fav)
        scored.append(
            {
                "provider": p,
                "distance_km": dist_km,
                "is_favorite": is_fav,
                **result,
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]
