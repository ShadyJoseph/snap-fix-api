from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Category, Office, Region
from .serializers import (
    CategorySerializer,
    OfficeDetailSerializer,
    OfficeListSerializer,
    RegionSerializer,
)


class CategoryListView(generics.ListAPIView):
    """GET /api/v1/core/categories/"""

    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return Category.objects.filter(is_active=True)


class RegionListView(generics.ListAPIView):
    """GET /api/v1/core/regions/"""

    serializer_class = RegionSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return Region.objects.filter(is_active=True)


class OfficeListView(generics.ListAPIView):
    """GET /api/v1/core/offices/"""

    serializer_class = OfficeListSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return Office.objects.filter(is_active=True).select_related("region")


class OfficeDetailView(generics.RetrieveAPIView):
    """GET /api/v1/core/offices/<id>/"""

    serializer_class = OfficeDetailSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "id"

    def get_queryset(self):
        return Office.objects.filter(is_active=True).select_related("region")


class NearestOfficeView(APIView):
    """
    GET /api/v1/core/offices/nearest/?lat=30.0444&lng=31.2357

    Returns the single closest active office to the given coordinates.
    """

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        lat = request.query_params.get("lat")
        lng = request.query_params.get("lng")

        if not lat or not lng:
            raise ValidationError("Both 'lat' and 'lng' query params are required.")

        try:
            user_location = Point(float(lng), float(lat), srid=4326)
        except (TypeError, ValueError) as e:
            raise ValidationError("'lat' and 'lng' must be valid numbers.") from e

        office = (
            Office.objects.filter(is_active=True, location__isnull=False)
            .select_related("region")
            .annotate(distance=Distance("location", user_location))
            .order_by("distance")
            .first()
        )

        if not office:
            return Response(
                {"detail": "No offices available at the moment."},
                status=status.HTTP_404_NOT_FOUND,
            )

        data = OfficeDetailSerializer(office).data
        data["distance_km"] = round(office.distance.km, 2)
        return Response(data)
