from rest_framework import serializers

from apps.core.serializers import CategorySerializer, RegionSerializer
from apps.customer.serializers import CustomerSerializer
from apps.provider.serializers import ProviderSerializer

from .models import Review, ServiceRequest


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
    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "status",
            "category",
            "region",
            "address",
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

    def create(self, validated_data):
        validated_data["customer"] = self.context["request"].user.customer
        return super().create(validated_data)


class ServiceRequestSerializer(serializers.ModelSerializer):
    """Full read serializer — used for list and action responses."""

    category = CategorySerializer(read_only=True)
    region = RegionSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    cancelled_by_display = serializers.CharField(
        source="get_cancelled_by_display", read_only=True
    )
    review = ReviewSerializer(read_only=True)

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "status",
            "status_display",
            "category",
            "region",
            "address",
            "latitude",
            "longitude",
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

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "status",
            "status_display",
            "category",
            "region",
            "address",
            "latitude",
            "longitude",
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

    def get_is_favorite_provider(self, obj):
        customer = self.context["request"].user.customer
        if not obj.provider_id:
            return False
        return customer.favorite_providers.filter(pk=obj.provider_id).exists()


class ProviderRequestDetailSerializer(serializers.ModelSerializer):
    """Full detail from the provider perspective — includes customer info + review."""

    category = CategorySerializer(read_only=True)
    region = RegionSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    customer = CustomerSerializer(read_only=True)
    review = ReviewSerializer(read_only=True)

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "status",
            "status_display",
            "category",
            "region",
            "address",
            "latitude",
            "longitude",
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
