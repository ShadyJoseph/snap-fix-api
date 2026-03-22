import uuid

from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Category, Office, Region


def create_category(**kwargs):
    defaults = {
        "name": "Plumbing",
        "slug": "plumbing",
        "icon": "🔧",
        "is_active": True,
        "order": 1,
    }
    defaults.update(kwargs)
    return Category.objects.create(**defaults)


def create_region(**kwargs):
    defaults = {
        "name": "Cairo",
        "slug": "cairo",
        "code": "CAI",
        "country": "Egypt",
        "location": Point(31.2357, 30.0444, srid=4326),
        "is_active": True,
    }
    defaults.update(kwargs)
    return Region.objects.create(**defaults)


def get_results(response):
    """Handle both paginated and non-paginated responses."""
    if isinstance(response.data, dict) and "results" in response.data:
        return response.data["results"]
    return response.data


class CategoryListTests(APITestCase):
    url = reverse("category-list")

    def setUp(self):
        Category.objects.all().delete()

    def test_returns_active_categories(self):
        create_category(name="Plumbing", slug="plumbing")
        create_category(name="Electrical", slug="electrical")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(get_results(response)), 2)

    def test_excludes_inactive_categories(self):
        create_category(name="Plumbing", slug="plumbing", is_active=True)
        create_category(name="Electrical", slug="electrical", is_active=False)
        response = self.client.get(self.url)
        self.assertEqual(len(get_results(response)), 1)
        self.assertEqual(get_results(response)[0]["name"], "Plumbing")

    def test_response_fields(self):
        create_category()
        response = self.client.get(self.url)
        fields = {"id", "name", "slug", "description", "icon", "order", "is_active"}
        self.assertEqual(set(get_results(response)[0].keys()), fields)

    def test_icon_is_emoji(self):
        create_category(icon="🔧")
        response = self.client.get(self.url)
        self.assertEqual(get_results(response)[0]["icon"], "🔧")

    def test_empty_list(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(get_results(response)), 0)

    def test_no_auth_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class RegionListTests(APITestCase):
    url = reverse("region-list")

    def setUp(self):
        Region.objects.all().delete()

    def test_returns_active_regions(self):
        create_region(name="Cairo", slug="cairo", code="CAI")
        create_region(name="Alexandria", slug="alexandria", code="ALX")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(get_results(response)), 2)

    def test_excludes_inactive_regions(self):
        create_region(name="Cairo", slug="cairo", code="CAI", is_active=True)
        create_region(name="Alexandria", slug="alexandria", code="ALX", is_active=False)
        response = self.client.get(self.url)
        self.assertEqual(len(get_results(response)), 1)
        self.assertEqual(get_results(response)[0]["name"], "Cairo")

    def test_response_fields(self):
        create_region()
        response = self.client.get(self.url)
        fields = {
            "id",
            "name",
            "slug",
            "code",
            "country",
            "latitude",
            "longitude",
            "is_active",
        }
        self.assertEqual(set(get_results(response)[0].keys()), fields)

    def test_location_returns_lat_lng(self):
        create_region(location=Point(31.2357, 30.0444, srid=4326))
        response = self.client.get(self.url)
        self.assertAlmostEqual(get_results(response)[0]["latitude"], 30.0444, places=3)
        self.assertAlmostEqual(get_results(response)[0]["longitude"], 31.2357, places=3)

    def test_region_without_location(self):
        create_region(location=None)
        response = self.client.get(self.url)
        self.assertIsNone(get_results(response)[0]["latitude"])
        self.assertIsNone(get_results(response)[0]["longitude"])

    def test_empty_list(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(get_results(response)), 0)

    def test_no_auth_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


def create_office(region, **kwargs):
    defaults = {
        "name": "Main Office",
        "address": "5 Tahrir Square, Cairo",
        "landmark": "Next to the Egyptian Museum",
        "location": Point(31.2357, 30.0444, srid=4326),
        "working_hours": "Sun–Thu 9:00 AM – 5:00 PM",
        "is_active": True,
    }
    defaults.update(kwargs)
    return Office.objects.create(region=region, **defaults)


class OfficeListTests(APITestCase):
    url = reverse("office-list")

    def setUp(self):
        Office.objects.all().delete()
        self.region = create_region()

    def test_returns_active_offices(self):
        create_office(self.region)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(get_results(response)), 1)

    def test_excludes_inactive_offices(self):
        create_office(self.region, is_active=True)
        create_office(self.region, name="Old Office", is_active=False)
        response = self.client.get(self.url)
        self.assertEqual(len(get_results(response)), 1)

    def test_location_returns_lat_lng(self):
        create_office(self.region, location=Point(31.2357, 30.0444, srid=4326))
        response = self.client.get(self.url)
        result = get_results(response)[0]
        self.assertAlmostEqual(result["latitude"], 30.0444, places=3)
        self.assertAlmostEqual(result["longitude"], 31.2357, places=3)

    def test_response_fields(self):
        create_office(self.region)
        response = self.client.get(self.url)
        expected = {
            "id",
            "name",
            "address",
            "landmark",
            "latitude",
            "longitude",
            "region_name",
            "working_hours",
        }
        self.assertEqual(set(get_results(response)[0].keys()), expected)

    def test_region_is_nested(self):
        create_office(self.region)
        response = self.client.get(self.url)
        self.assertEqual(get_results(response)[0]["region_name"], self.region.name)

    def test_no_auth_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class OfficeDetailTests(APITestCase):
    def setUp(self):
        Office.objects.all().delete()
        self.region = create_region()
        self.office = create_office(self.region)
        self.url = reverse("office-detail", kwargs={"id": self.office.id})

    def test_returns_office(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(self.office.id))

    def test_response_fields(self):
        response = self.client.get(self.url)
        expected = {
            "id",
            "name",
            "address",
            "landmark",
            "latitude",
            "longitude",
            "region",
            "working_hours",
            "is_active",
            "created_at",
        }
        self.assertEqual(set(response.data.keys()), expected)

    def test_region_is_fully_nested(self):
        response = self.client.get(self.url)
        region_fields = {
            "id",
            "name",
            "slug",
            "code",
            "country",
            "latitude",
            "longitude",
            "is_active",
        }
        self.assertEqual(set(response.data["region"].keys()), region_fields)

    def test_inactive_office_returns_404(self):
        self.office.is_active = False
        self.office.save()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_nonexistent_office_returns_404(self):
        url = reverse("office-detail", kwargs={"id": uuid.uuid4()})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_no_auth_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class NearestOfficeTests(APITestCase):
    url = "/api/v1/core/offices/nearest/"

    def setUp(self):
        Office.objects.all().delete()
        self.region = create_region()
        # Cairo office
        self.cairo = create_office(
            self.region,
            name="Cairo Office",
            location=Point(31.2357, 30.0444, srid=4326),
        )
        # Alexandria office — farther from Cairo coords
        self.alex = create_office(
            self.region,
            name="Alex Office",
            location=Point(29.9187, 31.2001, srid=4326),
        )

    def test_returns_nearest(self):
        response = self.client.get(self.url, {"lat": "30.0444", "lng": "31.2357"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Cairo Office")

    def test_includes_distance_km(self):
        response = self.client.get(self.url, {"lat": "30.0444", "lng": "31.2357"})
        self.assertIn("distance_km", response.data)
        self.assertIsInstance(response.data["distance_km"], float)

    def test_missing_params_returns_400(self):
        response = self.client.get(self.url, {"lat": "30.0444"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_params_returns_400(self):
        response = self.client.get(self.url, {"lat": "abc", "lng": "xyz"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_offices_returns_404(self):
        Office.objects.all().delete()
        response = self.client.get(self.url, {"lat": "30.0444", "lng": "31.2357"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_no_auth_required(self):
        response = self.client.get(self.url, {"lat": "30.0444", "lng": "31.2357"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
