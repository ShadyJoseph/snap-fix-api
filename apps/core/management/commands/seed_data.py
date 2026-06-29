"""
Seed the local / staging database with realistic demo data for manual testing.

Built on the shared helpers in the repo-root ``factories`` module so the seeded
shapes always match what the test suite uses.

The command is **idempotent**: users are keyed on deterministic ``@demo.local``
emails and created with get-or-create semantics, and service requests are topped
up to the requested count rather than duplicated. That makes it safe to run on
every deployment.

Usage:
    python manage.py seed_data
    python manage.py seed_data --customers 10 --providers 15 --requests 40
    python manage.py seed_data --clear           # wipe previously seeded demo data first
    python manage.py seed_data --force           # allow running when DEBUG is False

Everything it creates is tagged with the ``@demo.local`` email domain so
``--clear`` can remove it again without touching real data. Document/photo images
come from the committed ``apps/core/seed_assets/`` folder. Fixed login accounts
(password ``testpass123``):

    admin@demo.local      — superuser / staff
    customer@demo.local   — customer
    provider@demo.local   — verified provider
"""

from __future__ import annotations

import random
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

# Repo-root module: the directory holding manage.py is on sys.path, so the shared
# `factories.py` helpers import the same way they do in the test suite.
from factories import (
    DEFAULT_PASSWORD,
    make_category,
    make_completed_request,
    make_customer,
    make_onboarding,
    make_provider,
    make_region,
    make_review,
    make_service_request,
    make_staff,
)

DEMO_DOMAIN = "demo.local"

# Committed placeholder images (NOT the gitignored test-data/ OCR fixtures).
SEED_ASSETS = Path(__file__).resolve().parents[2] / "seed_assets"

# Real Cairo-area coordinates so the geo / radius logic behaves believably.
REGIONS = [
    {
        "name": "Cairo",
        "slug": "cairo",
        "code": "CAI",
        "location": Point(31.2357, 30.0444, srid=4326),
    },
    {
        "name": "Giza",
        "slug": "giza",
        "code": "GIZ",
        "location": Point(31.2089, 30.0131, srid=4326),
    },
    {
        "name": "Alexandria",
        "slug": "alexandria",
        "code": "ALX",
        "location": Point(29.9187, 31.2001, srid=4326),
    },
]

CATEGORIES = [
    {"name": "Plumbing", "slug": "plumbing", "icon": "🔧", "order": 1},
    {"name": "Electrical", "slug": "electrical", "icon": "⚡", "order": 2},
    {"name": "Carpentry", "slug": "carpentry", "icon": "🪚", "order": 3},
    {"name": "AC Repair", "slug": "ac-repair", "icon": "❄️", "order": 4},
    {"name": "Cleaning", "slug": "cleaning", "icon": "🧹", "order": 5},
    {"name": "Painting", "slug": "painting", "icon": "🎨", "order": 6},
]

REQUEST_TITLES = [
    ("Fix leaking kitchen sink", "Water pooling under the sink cabinet."),
    ("Install ceiling light fixture", "New LED fixture for the living room."),
    ("Repair broken cabinet door", "Hinge snapped on the upper kitchen cabinet."),
    ("AC not cooling", "Split unit runs but blows warm air."),
    ("Deep clean apartment", "Two-bedroom flat, move-out clean."),
    ("Paint the bedroom", "One coat of off-white over the current colour."),
    ("Unclog bathroom drain", "Slow drain in the main bathroom."),
    ("Replace power socket", "Socket sparks when plugging in appliances."),
]

FIRST_NAMES = [
    "Ahmed",
    "Mona",
    "Khaled",
    "Sara",
    "Omar",
    "Yasmin",
    "Hassan",
    "Nour",
    "Tarek",
    "Heba",
]
LAST_NAMES = [
    "Hassan",
    "Ibrahim",
    "Saleh",
    "Fouad",
    "Mansour",
    "Adel",
    "Naguib",
    "Rashad",
]

SERVICE_PHOTOS = ["service_photo_1.png", "service_photo_2.png", "service_photo_3.png"]


def load_asset(filename: str, upload_name: str | None = None) -> SimpleUploadedFile:
    """Read a committed seed image into a fresh upload object for an ImageField."""
    data = (SEED_ASSETS / filename).read_bytes()
    return SimpleUploadedFile(upload_name or filename, data, content_type="image/png")


def make_region_demo(spec: dict):
    """Region factory wrapper that pins real coordinates."""
    return make_region(
        name=spec["name"],
        slug=spec["slug"],
        code=spec["code"],
        location=spec["location"],
    )


class Command(BaseCommand):
    help = (
        "Seed the database with demo data for manual testing (built on factories.py)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--customers", type=int, default=6, help="Target number of customers."
        )
        parser.add_argument(
            "--providers",
            type=int,
            default=10,
            help="Target number of verified providers.",
        )
        parser.add_argument(
            "--requests",
            type=int,
            default=18,
            help="Target number of service requests.",
        )
        parser.add_argument(
            "--onboarding",
            type=int,
            default=3,
            help="Number of pending onboarding applications.",
        )
        parser.add_argument(
            "--seed", type=int, default=42, help="RNG seed for reproducible data."
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete previously seeded demo data (anything @demo.local) before seeding.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow running when settings.DEBUG is False (e.g. on a deployed staging env).",
        )

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["force"]:
            raise CommandError(
                "Refusing to seed with DEBUG=False. Re-run with --force if you really mean it."
            )
        if not SEED_ASSETS.is_dir():
            raise CommandError(f"Seed assets folder not found: {SEED_ASSETS}")

        random.seed(opts["seed"])

        if opts["clear"]:
            self._clear()

        with transaction.atomic():
            regions = [make_region_demo(r) for r in REGIONS]
            categories = [make_category(**c) for c in CATEGORIES]

            staff = self._fixed_staff()
            customers = self._make_customers(opts["customers"])
            providers = self._make_providers(opts["providers"], regions, categories)
            requests, photos = self._make_requests(
                opts["requests"], customers, providers, categories, regions
            )
            onboardings = self._make_onboardings(
                opts["onboarding"], regions, categories
            )

        self._summary(
            regions,
            categories,
            staff,
            customers,
            providers,
            requests,
            photos,
            onboardings,
        )

    # ── Builders ────────────────────────────────────────────────

    def _fixed_staff(self):
        from apps.staff.models import Staff

        email = f"admin@{DEMO_DOMAIN}"
        existing = Staff.objects.filter(email=email).first()
        if existing:
            return existing
        staff = make_staff(email=email, first_name="Demo", last_name="Admin")
        staff.is_staff = True
        staff.is_superuser = True
        staff.save(update_fields=["is_staff", "is_superuser"])
        return staff

    def _make_customers(self, n):
        from apps.customer.models import Customer

        specs = [(f"customer@{DEMO_DOMAIN}", "Demo", "Customer")]
        for i in range(1, max(1, n)):
            specs.append(
                (
                    f"customer{i:02d}@{DEMO_DOMAIN}",
                    FIRST_NAMES[i % len(FIRST_NAMES)],
                    LAST_NAMES[i % len(LAST_NAMES)],
                )
            )

        customers = []
        for email, first, last in specs:
            existing = Customer.objects.filter(email=email).first()
            customers.append(
                existing or make_customer(email=email, first_name=first, last_name=last)
            )
        return customers

    def _make_providers(self, n, regions, categories):
        from apps.provider.models import Provider

        specs = [(f"provider@{DEMO_DOMAIN}", "Demo", "Provider")]
        for i in range(1, max(1, n)):
            specs.append(
                (
                    f"provider{i:02d}@{DEMO_DOMAIN}",
                    FIRST_NAMES[i % len(FIRST_NAMES)],
                    LAST_NAMES[i % len(LAST_NAMES)],
                )
            )

        providers = []
        for email, first, last in specs:
            existing = Provider.objects.filter(email=email).first()
            if existing:
                providers.append(existing)
                continue
            provider = make_provider(
                email=email,
                first_name=first,
                last_name=last,
                active=True,
                verified=True,
            )
            provider.region = random.choice(regions)
            provider.service_radius = random.choice([5, 10, 15, 25])
            provider.is_available = True
            provider.years_of_experience = random.randint(1, 12)
            provider.hourly_rate = Decimal(
                random.choice(["100.00", "150.00", "200.00", "250.00"])
            )
            provider.bio = "Experienced local professional available for same-day jobs."
            provider.save()
            provider.categories.set(random.sample(categories, k=random.randint(1, 2)))
            providers.append(provider)
        return providers

    def _make_requests(self, n, customers, providers, categories, regions):
        from apps.booking.choices import (
            PaymentMethod,
            PaymentStatus,
            ServiceRequestStatus,
        )
        from apps.booking.models import ServiceRequest, ServiceRequestPhoto

        # Idempotent: only create the shortfall toward the target count.
        existing = ServiceRequest.objects.filter(
            customer__email__endswith=f"@{DEMO_DOMAIN}"
        ).count()
        need = max(0, n - existing)

        requests, photos = [], []
        if need:
            plan = (
                ["pending"] * max(1, need // 3)
                + ["assigned"] * max(1, need // 6)
                + ["completed"] * max(1, need // 3)
                + ["cancelled"] * max(1, need // 12)
            )
            plan = (plan * ((need // max(1, len(plan))) + 1))[:need]
            random.shuffle(plan)
        else:
            plan = []

        for state in plan:
            customer = random.choice(customers)
            category = random.choice(categories)
            region = random.choice(regions)
            title, description = random.choice(REQUEST_TITLES)
            preferred = timezone.now().date() + timezone.timedelta(
                days=random.randint(1, 21)
            )
            is_urgent = random.random() < 0.25

            # Pick a provider that actually serves this category, when possible.
            eligible = [
                p for p in providers if category in p.categories.all()
            ] or providers
            provider = random.choice(eligible)

            if state == "completed":
                sr = make_completed_request(
                    customer,
                    provider,
                    category,
                    region,
                    title=title,
                    description=description,
                    preferred_date=preferred,
                    is_urgent=is_urgent,
                )
                sr.final_price = Decimal(
                    random.choice(["180.00", "240.00", "320.00", "450.00"])
                )
                sr.payment_method = random.choice(
                    [PaymentMethod.CASH, PaymentMethod.CARD]
                )
                sr.payment_status = PaymentStatus.PAID
                sr.completed_at = timezone.now() - timezone.timedelta(
                    days=random.randint(0, 14)
                )
                sr.save()
                make_review(sr, customer, provider, rating=random.randint(3, 5))
            else:
                sr = make_service_request(
                    customer,
                    category,
                    region,
                    title=title,
                    description=description,
                    preferred_date=preferred,
                    is_urgent=is_urgent,
                )
                if state == "assigned":
                    sr.provider = provider
                    sr.status = ServiceRequestStatus.ASSIGNED
                    sr.assigned_at = timezone.now()
                    sr.save()
                elif state == "cancelled":
                    sr.status = ServiceRequestStatus.CANCELLED
                    sr.cancelled_at = timezone.now()
                    sr.save()

            # Attach 1–2 photos to ~60% of requests so the admin gallery has data.
            if random.random() < 0.6:
                for name in random.sample(SERVICE_PHOTOS, k=random.randint(1, 2)):
                    photos.append(
                        ServiceRequestPhoto.objects.create(
                            service_request=sr, image=load_asset(name)
                        )
                    )
            requests.append(sr)

        self._recalc_provider_stats(providers)
        return requests, photos

    def _recalc_provider_stats(self, providers):
        from django.db.models import Avg, Count

        for provider in providers:
            reviews = provider.reviews.aggregate(avg=Avg("rating"), n=Count("id"))
            completed = provider.service_requests.filter(status="completed").count()
            provider.completed_jobs = completed
            provider.total_jobs = completed
            provider.total_reviews = reviews["n"] or 0
            provider.average_rating = Decimal(str(round(reviews["avg"] or 0, 2)))
            provider.save(
                update_fields=[
                    "completed_jobs",
                    "total_jobs",
                    "total_reviews",
                    "average_rating",
                ]
            )

    def _make_onboardings(self, n, regions, categories):
        from apps.provider.models import Provider, ProviderOnboarding

        onboardings = []
        for i in range(n):
            email = f"applicant{i:02d}@{DEMO_DOMAIN}"
            existing = ProviderOnboarding.objects.filter(email=email).first()
            if existing:
                onboardings.append(existing)
                continue
            applicant = Provider.objects.filter(email=email).first() or make_provider(
                email=email,
                active=False,
                verified=False,
                first_name=FIRST_NAMES[i % len(FIRST_NAMES)],
                last_name=LAST_NAMES[i % len(LAST_NAMES)],
            )
            onb = make_onboarding(
                random.choice(regions),
                random.choice(categories),
                applicant=applicant,
                nid_front=load_asset("nid_front.png"),
                nid_back=load_asset("nid_back.png"),
                police_clearance_certificate=load_asset("police_clearance.png"),
                professional_certificate=load_asset("professional_cert.png"),
            )
            onboardings.append(onb)
        return onboardings

    # ── Maintenance ─────────────────────────────────────────────

    def _clear(self):
        from apps.booking.models import ServiceRequest
        from apps.customer.models import Customer
        from apps.provider.models import Provider, ProviderOnboarding

        self.stdout.write(
            self.style.WARNING(f"Clearing existing @{DEMO_DOMAIN} demo data…")
        )
        ProviderOnboarding.objects.filter(email__endswith=f"@{DEMO_DOMAIN}").delete()
        ServiceRequest.objects.filter(
            customer__email__endswith=f"@{DEMO_DOMAIN}"
        ).delete()
        Provider.objects.filter(email__endswith=f"@{DEMO_DOMAIN}").delete()
        Customer.objects.filter(email__endswith=f"@{DEMO_DOMAIN}").delete()

    # ── Output ──────────────────────────────────────────────────

    def _summary(
        self,
        regions,
        categories,
        staff,
        customers,
        providers,
        requests,
        photos,
        onboardings,
    ):
        w = self.stdout.write
        ok = self.style.SUCCESS
        w(ok("\n✓ Seeding complete\n"))
        w(f"  Regions:      {len(regions)}")
        w(f"  Categories:   {len(categories)}")
        w(f"  Customers:    {len(customers)}")
        w(f"  Providers:    {len(providers)}")
        w(f"  Requests:     +{len(requests)} created (topped up toward target)")
        w(f"  Photos:       +{len(photos)} attached")
        w(f"  Onboardings:  {len(onboardings)} (pending)")
        w(ok("\n  Login accounts (password: " + DEFAULT_PASSWORD + ")"))
        w(f"    admin@{DEMO_DOMAIN}      — superuser / staff")
        w(f"    customer@{DEMO_DOMAIN}   — customer")
        w(f"    provider@{DEMO_DOMAIN}   — verified provider\n")
