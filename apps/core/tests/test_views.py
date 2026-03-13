from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Category, Region


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
