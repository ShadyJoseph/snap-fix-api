from rest_framework import serializers

from apps.core.serializers import CategorySerializer, RegionSerializer

from .models import ServiceRequest


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
        read_only_fields = ["id", "status"]  # status is read-only on create

    def create(self, validated_data):
        validated_data["customer"] = self.context["request"].user.customer
        return super().create(validated_data)


class ServiceRequestSerializer(serializers.ModelSerializer):
    """Full read serializer — used for detail and list views."""

    category = CategorySerializer(read_only=True)
    region = RegionSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    cancelled_by_display = serializers.CharField(
        source="get_cancelled_by_display", read_only=True
    )

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
            "created_at",
            "assigned_at",
            "confirmed_at",
            "started_at",
            "completed_at",
            "cancelled_at",
        ]


class ServiceRequestCompleteSerializer(serializers.Serializer):
    """Provider submits final price on completion."""

    final_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0, required=False
    )


class ServiceRequestCancelSerializer(serializers.Serializer):
    """Customer or provider cancels with a reason."""

    reason = serializers.CharField(required=False, allow_blank=True)
