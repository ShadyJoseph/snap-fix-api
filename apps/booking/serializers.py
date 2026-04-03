import math

from django.contrib.gis.geos import Point
from rest_framework import serializers

from apps.core.serializers import CategorySerializer, RegionSerializer
from apps.customer.serializers import CustomerSerializer
from apps.provider.serializers import ProviderSerializer

from .models import Review, ServiceRequest

# Average urban travel speed used for ETA estimation.
_TRAVEL_SPEED_KMH = 30


def _haversine_km(lat1, lon1, lat2, lon2):
    """Straight-line distance between two WGS-84 coordinates in kilometres."""
    r = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _travel_info(from_point, to_point):
    """
    Return (distance_km, eta_minutes) between two PointField values.
    Returns (None, None) if the provider has no stored location yet.
    `to_point` (the job location) is always set on new requests.
    """
    if not from_point or not to_point:
        return None, None
    km = _haversine_km(from_point.y, from_point.x, to_point.y, to_point.x)
    eta = math.ceil(km / _TRAVEL_SPEED_KMH * 60)
    return round(km, 2), eta


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ["id", "rating", "comment", "created_at"]
        read_only_fields = ["id", "created_at"]


class ReviewCreateSerializer(serializers.Serializer):
    """Customer submits rating + optional comment."""

    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True)


class ServiceRequestCreateSerializer(serializers.ModelSerializer):
    latitude = serializers.FloatField(
        write_only=True,
        help_text="WGS-84 latitude of the service location.",
    )
    longitude = serializers.FloatField(
        write_only=True,
        help_text="WGS-84 longitude of the service location.",
    )

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "status",
            "category",
            "region",
            "address",
            "floor_number",
            "apartment_number",
            "special_mark",
            "latitude",
            "longitude",
            "title",
            "description",
            "is_urgent",
            "preferred_date",
            "preferred_time",
            "estimated_price",
        ]
        read_only_fields = ["id", "status"]

    def validate_latitude(self, value):
        if not (-90 <= value <= 90):
            raise serializers.ValidationError("Must be between -90 and 90.")
        return value

    def validate_longitude(self, value):
        if not (-180 <= value <= 180):
            raise serializers.ValidationError("Must be between -180 and 180.")
        return value

    def validate(self, data):
        lat = data.pop("latitude")
        lng = data.pop("longitude")
        data["location"] = Point(x=lng, y=lat, srid=4326)
        return data

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep["latitude"] = instance.location.y
        rep["longitude"] = instance.location.x
        return rep


class ServiceRequestSerializer(serializers.ModelSerializer):
    """Full read serializer — used for list and action responses."""

    category = CategorySerializer(read_only=True)
    region = RegionSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    cancelled_by_display = serializers.CharField(
        source="get_cancelled_by_display", read_only=True
    )
    review = ReviewSerializer(read_only=True)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    # Populated by DB annotation in the open-pool view.
    distance_km = serializers.SerializerMethodField()
    # Provider's current distance + ETA to the service location.
    provider_distance_km = serializers.SerializerMethodField()
    provider_eta_minutes = serializers.SerializerMethodField()

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "status",
            "status_display",
            "category",
            "region",
            "address",
            "floor_number",
            "apartment_number",
            "special_mark",
            "latitude",
            "longitude",
            "distance_km",
            "provider_distance_km",
            "provider_eta_minutes",
            "title",
            "description",
            "is_urgent",
            "preferred_date",
            "preferred_time",
            "estimated_price",
            "final_price",
            "cancelled_by",
            "cancelled_by_display",
            "cancellation_reason",
            "decline_reason",
            "created_at",
            "assigned_at",
            "confirmed_at",
            "started_at",
            "completed_at",
            "cancelled_at",
            "declined_at",
            "review",
        ]

    def get_latitude(self, obj):
        return obj.location.y

    def get_longitude(self, obj):
        return obj.location.x

    def get_distance_km(self, obj):
        """Populated only when the queryset annotates a `distance` value (provider open pool)."""
        if hasattr(obj, "distance") and obj.distance is not None:
            return round(obj.distance.km, 2)
        return None

    def get_provider_distance_km(self, obj):
        provider_loc = (
            obj.provider.location if obj.provider_id and obj.provider else None
        )
        km, _ = _travel_info(provider_loc, obj.location)
        return km

    def get_provider_eta_minutes(self, obj):
        provider_loc = (
            obj.provider.location if obj.provider_id and obj.provider else None
        )
        _, eta = _travel_info(provider_loc, obj.location)
        return eta


class ServiceRequestCompleteSerializer(serializers.Serializer):
    """Provider submits final price on completion."""

    final_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0, required=False
    )


class ServiceRequestCancelSerializer(serializers.Serializer):
    """Customer or provider cancels with an optional reason."""

    reason = serializers.CharField(required=False, allow_blank=True)


class ServiceRequestDeclineSerializer(serializers.Serializer):
    """Provider declines with an optional reason."""

    reason = serializers.CharField(required=False, allow_blank=True)


# ── History detail (full, role-aware) ────────────────────────


class CustomerRequestDetailSerializer(serializers.ModelSerializer):
    """Full detail from the customer perspective — includes provider info + review."""

    category = CategorySerializer(read_only=True)
    region = RegionSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    provider = ProviderSerializer(read_only=True)
    review = ReviewSerializer(read_only=True)
    is_favorite_provider = serializers.SerializerMethodField()
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    provider_distance_km = serializers.SerializerMethodField()
    provider_eta_minutes = serializers.SerializerMethodField()

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "status",
            "status_display",
            "category",
            "region",
            "address",
            "floor_number",
            "apartment_number",
            "special_mark",
            "latitude",
            "longitude",
            "provider_distance_km",
            "provider_eta_minutes",
            "title",
            "description",
            "is_urgent",
            "preferred_date",
            "preferred_time",
            "estimated_price",
            "final_price",
            "cancellation_reason",
            "decline_reason",
            "created_at",
            "assigned_at",
            "confirmed_at",
            "started_at",
            "completed_at",
            "cancelled_at",
            "provider",
            "review",
            "is_favorite_provider",
        ]

    def get_latitude(self, obj):
        return obj.location.y

    def get_longitude(self, obj):
        return obj.location.x

    def get_is_favorite_provider(self, obj):
        customer = self.context["request"].user.customer
        if not obj.provider_id:
            return False
        return customer.favorite_providers.filter(pk=obj.provider_id).exists()

    def get_provider_distance_km(self, obj):
        provider_loc = (
            obj.provider.location if obj.provider_id and obj.provider else None
        )
        km, _ = _travel_info(provider_loc, obj.location)
        return km

    def get_provider_eta_minutes(self, obj):
        provider_loc = (
            obj.provider.location if obj.provider_id and obj.provider else None
        )
        _, eta = _travel_info(provider_loc, obj.location)
        return eta


class ProviderRequestDetailSerializer(serializers.ModelSerializer):
    """Full detail from the provider perspective — includes customer info + review."""

    category = CategorySerializer(read_only=True)
    region = RegionSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    customer = CustomerSerializer(read_only=True)
    review = ReviewSerializer(read_only=True)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    # From the provider's perspective: how far am I from the job right now?
    distance_to_job_km = serializers.SerializerMethodField()
    eta_to_job_minutes = serializers.SerializerMethodField()

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "status",
            "status_display",
            "category",
            "region",
            "address",
            "floor_number",
            "apartment_number",
            "special_mark",
            "latitude",
            "longitude",
            "distance_to_job_km",
            "eta_to_job_minutes",
            "title",
            "description",
            "is_urgent",
            "preferred_date",
            "preferred_time",
            "estimated_price",
            "final_price",
            "created_at",
            "assigned_at",
            "confirmed_at",
            "started_at",
            "completed_at",
            "cancelled_at",
            "customer",
            "review",
        ]

    def get_latitude(self, obj):
        return obj.location.y

    def get_longitude(self, obj):
        return obj.location.x

    def get_distance_to_job_km(self, obj):
        provider_loc = (
            obj.provider.location if obj.provider_id and obj.provider else None
        )
        km, _ = _travel_info(provider_loc, obj.location)
        return km

    def get_eta_to_job_minutes(self, obj):
        provider_loc = (
            obj.provider.location if obj.provider_id and obj.provider else None
        )
        _, eta = _travel_info(provider_loc, obj.location)
        return eta
