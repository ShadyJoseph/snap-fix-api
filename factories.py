"""
Unified model factories for local shell testing.

Usage (Django shell):
    python manage.py shell
    from factories import *

    # --- Quick scaffold ---
    region   = make_region()
    category = make_category()
    customer = make_customer()
    provider = make_provider(active=True, verified=True)
    provider.categories.add(category)

    sr = make_service_request(customer, category, region)

    # --- Staff / onboarding ---
    staff  = make_staff()
    onb    = make_onboarding(region, category, applicant=provider)

    # --- Completed flow ---
    sr = make_completed_request(customer, provider, category, region)
    review = make_review(sr, customer, provider)

    # --- Images (for ImageField testing) ---
    img = make_image()
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.gis.geos import Point

# ── Constants ──────────────────────────────────────────────────────────────────

CAIRO = Point(31.2357, 30.0444, srid=4326)
DEFAULT_PASSWORD = "testpass123"  # noqa: S105


# ── Image helper ───────────────────────────────────────────────────────────────


def make_image(name: str = "photo.png"):
    """Return a minimal valid 1×1 PNG as a SimpleUploadedFile."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (1, 1), color=(255, 255, 255)).save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


# ── Core ───────────────────────────────────────────────────────────────────────


def make_category(**kwargs):
    """
    Get or create a Category.

    Examples:
        make_category()
        make_category(name="Electrical", slug="electrical", icon="⚡")
    """
    from apps.core.models import Category

    uid = uuid.uuid4().hex[:6]
    defaults = {
        "name": f"Category {uid}",
        "slug": f"category-{uid}",
        "icon": "🔧",
        "is_active": True,
        "order": 1,
    }
    defaults.update(kwargs)
    obj, _ = Category.objects.get_or_create(slug=defaults["slug"], defaults=defaults)
    return obj


def make_region(**kwargs):
    """
    Get or create a Region.

    Examples:
        make_region()
        make_region(name="Alexandria", slug="alex", code="ALX", country="Egypt")
    """
    from apps.core.models import Region

    uid = uuid.uuid4().hex[:6]
    defaults = {
        "name": f"Region {uid}",
        "slug": f"region-{uid}",
        "code": f"RGN{uid[:3].upper()}",
        "country": "Egypt",
        "location": CAIRO,
        "is_active": True,
    }
    defaults.update(kwargs)
    obj, _ = Region.objects.get_or_create(slug=defaults["slug"], defaults=defaults)
    return obj


def make_office(region, **kwargs):
    """
    Create an Office linked to a region.

    Examples:
        office = make_office(region)
        office = make_office(region, name="Branch Office", working_hours="Mon-Fri 9-5")
    """
    from apps.core.models import Office

    defaults = {
        "name": "Main Office",
        "address": "5 Tahrir Square, Cairo",
        "landmark": "Next to the Egyptian Museum",
        "location": CAIRO,
        "working_hours": "Sun-Thu 9:00 AM - 5:00 PM",
        "is_active": True,
    }
    defaults.update(kwargs)
    return Office.objects.create(region=region, **defaults)


# ── Users ──────────────────────────────────────────────────────────────────────


def make_customer(**kwargs):
    """
    Create a Customer (active by default).

    Examples:
        make_customer()
        make_customer(email="alice@test.com", first_name="Alice")
    """
    from apps.customer.models import Customer

    uid = uuid.uuid4().hex[:6]
    defaults = {
        "email": f"customer_{uid}@test.com",
        "first_name": "Test",
        "last_name": "Customer",
        "password": DEFAULT_PASSWORD,
        "is_active": True,
    }
    defaults.update(kwargs)
    return Customer.objects.create_user(**defaults)


def make_provider(
    active: bool = True,
    verified: bool = True,
    email: str | None = None,
    password: str = DEFAULT_PASSWORD,
    **kwargs,
):
    """
    Create a Provider.

    Parameters:
        active   – sets is_active (default True for shell convenience)
        verified – sets verification_status to VERIFIED when True, PENDING otherwise
        email    – auto-generated if omitted

    Examples:
        make_provider()
        make_provider(active=False, verified=False)   # simulates fresh registration
        make_provider(email="jane@test.com")
    """
    from apps.provider.choices import ProviderVerificationStatus
    from apps.provider.models import Provider

    uid = uuid.uuid4().hex[:6]
    vstatus = (
        ProviderVerificationStatus.VERIFIED
        if verified
        else ProviderVerificationStatus.PENDING
    )
    defaults = {
        "email": email or f"provider_{uid}@test.com",
        "first_name": "Test",
        "last_name": "Provider",
        "password": password,
        "is_active": active,
        "verification_status": vstatus,
    }
    defaults.update(kwargs)
    return Provider.objects.create_user(**defaults)


def make_staff(**kwargs):
    """
    Create a Staff user.

    Examples:
        make_staff()
        make_staff(email="ops@company.com")
    """
    from apps.staff.models import Staff

    uid = uuid.uuid4().hex[:6]
    defaults = {
        "email": f"staff_{uid}@test.com",
        "password": DEFAULT_PASSWORD,
        "first_name": "Staff",
        "last_name": "User",
    }
    defaults.update(kwargs)
    return Staff.objects.create_user(**defaults)


# ── Booking ────────────────────────────────────────────────────────────────────


def make_service_request(customer, category, region, **kwargs):
    """
    Create a ServiceRequest in PENDING status.

    Examples:
        sr = make_service_request(customer, category, region)
        sr = make_service_request(customer, category, region, is_urgent=True)
        sr = make_service_request(customer, category, region,
                                  payment_method="cash",
                                  preferred_date="2026-08-01")
    """
    from apps.booking.models import ServiceRequest

    defaults = {
        "title": "Fix leaking pipe",
        "description": "Pipe under sink is leaking",
        "address": "123 Test St",
        "floor_number": "3",
        "apartment_number": "12",
        "special_mark": "Blue door on the left",
        "location": CAIRO,
        "preferred_date": "2026-08-01",
        "preferred_time": "10:00:00",
        "is_urgent": False,
    }
    defaults.update(kwargs)
    return ServiceRequest.objects.create(
        customer=customer, category=category, region=region, **defaults
    )


def make_completed_request(customer, provider, category, region, **kwargs):
    """
    Create a ServiceRequest already in COMPLETED state with a provider assigned.

    Examples:
        sr = make_completed_request(customer, provider, category, region)
    """
    from apps.booking.choices import ServiceRequestStatus

    sr = make_service_request(customer, category, region, **kwargs)
    sr.status = ServiceRequestStatus.COMPLETED
    sr.provider = provider
    sr.save()
    return sr


def make_review(
    service_request, customer, provider, rating: int = 4, comment: str = "Good work"
):
    """
    Create a Review for a completed ServiceRequest.

    Examples:
        review = make_review(sr, customer, provider)
        review = make_review(sr, customer, provider, rating=5, comment="Excellent!")
    """
    from apps.booking.models import Review

    return Review.objects.create(
        service_request=service_request,
        customer=customer,
        provider=provider,
        rating=rating,
        comment=comment,
    )


# ── Provider onboarding ────────────────────────────────────────────────────────


def make_onboarding(
    region, category, applicant=None, email: str | None = None, **kwargs
):
    """
    Create a ProviderOnboarding application.

    If `applicant` is provided the application is linked to that pre-registered
    provider. Pass `email` explicitly to test flows without an applicant.

    Examples:
        provider = make_provider(active=False, verified=False)
        onb = make_onboarding(region, category, applicant=provider)

        # No linked provider (edge-case testing)
        onb = make_onboarding(region, category, email="new@test.com")
    """
    from apps.provider.models import ProviderOnboarding

    uid = uuid.uuid4().hex[:6]
    resolved_email = email or (
        applicant.email if applicant else f"provider_{uid}@test.com"
    )
    dob = date.today() - timedelta(days=365 * 25)

    defaults = {
        "first_name": "Jane",
        "last_name": "Smith",
        "email": resolved_email,
        "phone": "01012345678",
        "date_of_birth": dob,
        "address": "123 Cairo St",
        "hourly_rate": Decimal("150.00"),
        "years_of_experience": 3,
        "nid_front": make_image("nid_front.png"),
        "nid_back": make_image("nid_back.png"),
        "police_clearance_certificate": make_image("pcc.png"),
    }
    defaults.update(kwargs)

    obj = ProviderOnboarding(region=region, category=category, **defaults)
    if applicant:
        obj.applicant = applicant
    obj.save()
    return obj


# ── Full scaffold ──────────────────────────────────────────────────────────────


def scaffold():
    """
    Create a complete set of linked objects for a quick interactive session.

    Returns a dict with keys: region, category, customer, provider, service_request.

    Example:
        d = scaffold()
        d["provider"].categories.add(d["category"])
        sr = d["service_request"]
    """
    region = make_region(name="Cairo", slug="cairo", code="CAI")
    category = make_category(name="Plumbing", slug="plumbing")
    customer = make_customer(email="customer@test.com")
    provider = make_provider(email="provider@test.com")
    provider.categories.add(category)
    sr = make_service_request(customer, category, region)

    return {
        "region": region,
        "category": category,
        "customer": customer,
        "provider": provider,
        "service_request": sr,
    }
