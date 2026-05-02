import math

from django.contrib.gis.geos import Point
from rest_framework import serializers

from apps.core.serializers import CategorySerializer, RegionSerializer
from apps.customer.serializers import CustomerSerializer
from apps.provider.serializers import ProviderSerializer

from .choices import BookingMode, PaymentMethod
from .models import Review, ServiceRequest, ServiceRequestPhoto
from .utils import haversine_km

_TRAVEL_SPEED_KMH = 30


def _travel_info(from_point, to_point):
    if not from_point or not to_point:
        return None, None
    km = haversine_km(from_point.y, from_point.x, to_point.y, to_point.x)
    eta = math.ceil(km / _TRAVEL_SPEED_KMH * 60)
    return round(km, 2), eta


# ── Shared payment fields ─────────────────────────────────────────────────────

PAYMENT_READ_FIELDS = [
    "payment_method",
    "payment_method_display",
    "wallet_amount",
    "card_amount",  # computed property
    "payment_status",
    "payment_status_display",
]


# ── Small reusables ───────────────────────────────────────────────────────────


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ["id", "rating", "comment", "created_at"]
        read_only_fields = ["id", "created_at"]


class ReviewCreateSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True)


class ServiceRequestPhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceRequestPhoto
        fields = ["id", "image", "uploaded_at"]
        read_only_fields = ["id", "uploaded_at"]


# ── Create ────────────────────────────────────────────────────────────────────


class ServiceRequestCreateSerializer(serializers.ModelSerializer):
    """
    Write serializer used for POST /requests/.

    Payment split rules:
      • wallet_amount defaults to 0.
      • payment_method describes how the NON-wallet portion is paid:
          WALLET → entire bill from wallet (wallet_amount == estimated_price or unknown yet)
          CASH   → remainder collected by provider
          CARD   → remainder charged via Stripe
      • Wallet balance is validated here against estimated_price (if provided).
        It is re-validated at quote approval against the real final_price.
    """

    latitude = serializers.FloatField(write_only=True)
    longitude = serializers.FloatField(write_only=True)

    booking_mode = serializers.ChoiceField(
        choices=BookingMode.choices,
        default=BookingMode.BROADCAST,
        required=False,
        write_only=True,
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
            "payment_method",
            "wallet_amount",
            "booking_mode",
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
        # Build Point from lat/lng.
        lat = data.pop("latitude")
        lng = data.pop("longitude")
        data["location"] = Point(x=lng, y=lat, srid=4326)

        wallet_amount = data.get("wallet_amount", 0) or 0
        payment_method = data.get("payment_method", PaymentMethod.CASH)
        estimated_price = data.get("estimated_price")

        # wallet_amount must be non-negative.
        if wallet_amount < 0:
            raise serializers.ValidationError(
                {"wallet_amount": "Wallet amount cannot be negative."}
            )

        # For WALLET method, wallet_amount should cover the full cost.
        # We can only enforce this against estimated_price here (real price isn't set yet).
        if payment_method == PaymentMethod.WALLET and estimated_price is not None:
            if wallet_amount < estimated_price:
                # Auto-fill: if customer chose WALLET, treat wallet_amount as full price.
                wallet_amount = estimated_price
                data["wallet_amount"] = estimated_price

        # Validate wallet balance if wallet is used.
        if wallet_amount > 0:
            request = self.context.get("request")
            if request and hasattr(request.user, "customer"):
                customer = request.user.customer
                if customer.wallet_balance < wallet_amount:
                    raise serializers.ValidationError(
                        {
                            "wallet_amount": (
                                f"Insufficient wallet balance. "
                                f"Required: {wallet_amount}, "
                                f"available: {customer.wallet_balance}."
                            )
                        }
                    )

        return data

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep["latitude"] = instance.location.y
        rep["longitude"] = instance.location.x
        return rep


# ── Direct booking create ─────────────────────────────────────────────────────


class DirectBookingCreateSerializer(ServiceRequestCreateSerializer):
    """
    Extends the standard create serializer with a required provider_id.

    provider_id is write-only and must be popped from validated_data before
    serializer.save() so it is not forwarded to Model.objects.create().
    All provider validation (favorites, verified, available, category) is
    performed in the view, which has access to the authenticated customer.
    """

    provider_id = serializers.UUIDField(write_only=True)

    class Meta(ServiceRequestCreateSerializer.Meta):
        fields = ServiceRequestCreateSerializer.Meta.fields + ["provider_id"]


# ── Recommended booking create ────────────────────────────────────────────────


class RecommendedBookingCreateSerializer(ServiceRequestCreateSerializer):
    """
    Same as the standard create serializer but requires a provider_id.

    Validation (verified, available, offers category) is done in the view.
    No favourite-list check — the AI recommended this provider.

    booking_mode is excluded — the view always stamps RECOMMENDED at save time,
    so accepting it from the request body would be misleading.
    """

    provider_id = serializers.UUIDField(write_only=True)

    class Meta(ServiceRequestCreateSerializer.Meta):
        fields = [
            f for f in ServiceRequestCreateSerializer.Meta.fields if f != "booking_mode"
        ] + ["provider_id"]


# ── Recommended provider output ───────────────────────────────────────────────


class RecommendedProviderSerializer(serializers.Serializer):
    """Read-only serializer for a single recommendation result."""

    id = serializers.UUIDField(source="provider.pk")
    full_name = serializers.SerializerMethodField()
    business_name = serializers.CharField(source="provider.business_name")
    average_rating = serializers.DecimalField(
        source="provider.average_rating", max_digits=3, decimal_places=2
    )
    total_reviews = serializers.IntegerField(source="provider.total_reviews")
    completed_jobs = serializers.IntegerField(source="provider.completed_jobs")
    hourly_rate = serializers.DecimalField(
        source="provider.hourly_rate", max_digits=10, decimal_places=2, allow_null=True
    )
    years_of_experience = serializers.IntegerField(
        source="provider.years_of_experience"
    )
    acceptance_rate = serializers.SerializerMethodField()
    distance_km = serializers.FloatField()
    is_favorite = serializers.BooleanField()
    score = serializers.FloatField()
    signals = serializers.DictField()
    reason = serializers.CharField(default="")

    def get_full_name(self, obj):
        return obj["provider"].get_full_name()

    def get_acceptance_rate(self, obj):
        return obj["provider"].acceptance_rate


# ── Full read serializer ──────────────────────────────────────────────────────


class ServiceRequestSerializer(serializers.ModelSerializer):
    """Full read serializer — used for list and action responses."""

    category = CategorySerializer(read_only=True)
    region = RegionSerializer(read_only=True)
    photos = ServiceRequestPhotoSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    cancelled_by_display = serializers.CharField(
        source="get_cancelled_by_display", read_only=True
    )
    payment_method_display = serializers.CharField(
        source="get_payment_method_display", read_only=True
    )
    payment_status_display = serializers.CharField(
        source="get_payment_status_display", read_only=True
    )
    # Computed: final_price − wallet_amount
    card_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    review = ReviewSerializer(read_only=True)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    distance_km = serializers.SerializerMethodField()
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
            "photos",
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
            "quoted_price",
            "final_price",
            # Payment split
            "payment_method",
            "payment_method_display",
            "wallet_amount",
            "card_amount",
            "payment_status",
            "payment_status_display",
            # Audit
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
            "booking_mode",
        ]

    def get_latitude(self, obj):
        return obj.location.y

    def get_longitude(self, obj):
        return obj.location.x

    def get_distance_km(self, obj):
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


# ── Action serializers ────────────────────────────────────────────────────────


class ServiceRequestCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class ServiceRequestDeclineSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class ProviderQuoteSerializer(serializers.Serializer):
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)


class CustomerApproveQuoteSerializer(serializers.Serializer):
    """
    Customer adjusts their payment split when approving a quote.

    Fields:
      wallet_amount — how much to deduct from wallet (0 = none).
      payment_method — how to pay the remainder (CASH or CARD).
                       Pass WALLET if the full amount comes from the wallet.

    Both fields are optional. When omitted, the view preserves the values
    already stored on the service request (set at booking time).
    Validation is intentionally light here; the model's approve_quote()
    performs the authoritative balance check inside a row lock.
    """

    wallet_amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        required=False,
    )
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices,
        required=False,
    )

    def validate(self, data):
        wallet_amount = data.get("wallet_amount", 0) or 0
        if wallet_amount < 0:
            raise serializers.ValidationError(
                {"wallet_amount": "Wallet amount cannot be negative."}
            )
        return data


class InitiateCardPaymentSerializer(serializers.Serializer):
    """
    Customer provides a Stripe PaymentMethod ID to attach to the request.
    This is used to create/update the PaymentIntent before job completion.
    """

    stripe_payment_method_id = serializers.CharField(
        max_length=255,
        help_text="Stripe PaymentMethod ID (pm_xxx) from the client SDK.",
    )
    return_url = serializers.CharField(
        max_length=2048,
        help_text="Deep link or URL to redirect the customer after payment (required by Stripe). Supports custom schemes (e.g. snapfix://payment/complete).",
    )


# ── History detail serializers (role-aware) ───────────────────────────────────


class CustomerRequestDetailSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    region = RegionSerializer(read_only=True)
    photos = ServiceRequestPhotoSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    provider = ProviderSerializer(read_only=True)
    review = ReviewSerializer(read_only=True)
    is_favorite_provider = serializers.SerializerMethodField()
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    provider_distance_km = serializers.SerializerMethodField()
    provider_eta_minutes = serializers.SerializerMethodField()
    payment_method_display = serializers.CharField(
        source="get_payment_method_display", read_only=True
    )
    payment_status_display = serializers.CharField(
        source="get_payment_status_display", read_only=True
    )
    card_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "status",
            "status_display",
            "category",
            "region",
            "photos",
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
            "quoted_price",
            "final_price",
            "payment_method",
            "payment_method_display",
            "wallet_amount",
            "card_amount",
            "payment_status",
            "payment_status_display",
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
    category = CategorySerializer(read_only=True)
    region = RegionSerializer(read_only=True)
    photos = ServiceRequestPhotoSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    customer = CustomerSerializer(read_only=True)
    review = ReviewSerializer(read_only=True)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    distance_to_job_km = serializers.SerializerMethodField()
    eta_to_job_minutes = serializers.SerializerMethodField()
    payment_method_display = serializers.CharField(
        source="get_payment_method_display", read_only=True
    )
    payment_status_display = serializers.CharField(
        source="get_payment_status_display", read_only=True
    )
    card_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "status",
            "status_display",
            "category",
            "region",
            "photos",
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
            "quoted_price",
            "final_price",
            "payment_method",
            "payment_method_display",
            "wallet_amount",
            "card_amount",
            "payment_status",
            "payment_status_display",
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
