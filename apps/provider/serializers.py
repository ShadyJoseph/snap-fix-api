from django.contrib.auth import authenticate
from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework import serializers

from apps.user.models import User

from .choices import ProviderVerificationStatus
from .models import Provider, ProviderOnboarding


class ProviderRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = Provider
        fields = ["first_name", "last_name", "email", "phone", "password"]

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already registered.")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        # is_active=True so the provider can authenticate for the onboarding API.
        # verification_status=PENDING gates access to active-provider features.
        return Provider.objects.create_user(  # type: ignore
            **validated_data,
            password=password,
            is_active=True,
            verification_status=ProviderVerificationStatus.PENDING,
        )


class ProviderLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(email=data["email"], password=data["password"])

        if not user or not isinstance(user, User):
            raise serializers.ValidationError("Invalid credentials.")

        if not user.is_active:
            raise serializers.ValidationError("Account is disabled.")

        if not hasattr(user, "provider"):
            raise serializers.ValidationError("No provider account found.")

        if user.provider.verification_status == ProviderVerificationStatus.PENDING:
            raise serializers.ValidationError(
                "Your application is still under review. "
                "You will be notified once it is approved."
            )

        if user.provider.verification_status != ProviderVerificationStatus.VERIFIED:
            raise serializers.ValidationError("Provider account is not verified.")

        data["user"] = user
        return data


class ProviderSerializer(serializers.ModelSerializer):
    """Minimal read-only serializer — used on login response and booking views."""

    completion_rate = serializers.SerializerMethodField()
    rating = serializers.FloatField(read_only=True)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    class Meta:
        model = Provider
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "phone",
            "business_name",
            "bio",
            "verification_status",
            "is_available",
            "rating",
            "total_reviews",
            "total_jobs",
            "completed_jobs",
            "completion_rate",
            "available_balance",
            "total_earnings",
            "hourly_rate",
            "years_of_experience",
            "latitude",
            "longitude",
            "date_joined",
        ]
        read_only_fields = fields

    def get_completion_rate(self, obj):
        return obj.get_completion_rate()

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None


class ProviderProfileSerializer(serializers.ModelSerializer):
    """Full serializer for the authenticated provider's own profile (GET /me/)."""

    completion_rate = serializers.SerializerMethodField()
    rating = serializers.FloatField(read_only=True)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    class Meta:
        model = Provider
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "phone",
            "profile_picture",
            "address",
            "latitude",
            "longitude",
            "business_name",
            "bio",
            "hourly_rate",
            "years_of_experience",
            "region",
            "categories",
            "verification_status",
            "is_available",
            "rating",
            "total_reviews",
            "total_jobs",
            "completed_jobs",
            "completion_rate",
            "available_balance",
            "total_earnings",
            "date_joined",
        ]
        read_only_fields = fields

    def get_completion_rate(self, obj):
        return obj.get_completion_rate()

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None


class ProviderUpdateSerializer(serializers.ModelSerializer):
    """PATCH /me/ — only non-sensitive profile fields."""

    latitude = serializers.FloatField(required=False, allow_null=True, write_only=True)
    longitude = serializers.FloatField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = Provider
        fields = [
            "first_name",
            "last_name",
            "phone",
            "profile_picture",
            "address",
            "business_name",
            "bio",
            "hourly_rate",
            "years_of_experience",
            "is_available",
            "latitude",
            "longitude",
        ]

    def validate(self, data):
        lat = data.pop("latitude", None)
        lng = data.pop("longitude", None)
        if lat is not None and lng is not None:
            data["location"] = Point(x=lng, y=lat, srid=4326)
        elif (lat is None) != (lng is None):
            raise serializers.ValidationError(
                "Provide both latitude and longitude, or neither."
            )
        return data


class ProviderLocationSerializer(serializers.Serializer):
    """
    PATCH /me/location/
    Lightweight endpoint for frequent location pings (e.g. every 60 s).
    Accepts latitude + longitude and updates the provider's stored location.
    """

    latitude = serializers.FloatField()
    longitude = serializers.FloatField()

    def validate_latitude(self, value):
        if not (-90 <= value <= 90):
            raise serializers.ValidationError("Latitude must be between -90 and 90.")
        return value

    def validate_longitude(self, value):
        if not (-180 <= value <= 180):
            raise serializers.ValidationError("Longitude must be between -180 and 180.")
        return value

    def save(self, provider):
        provider.location = Point(
            x=self.validated_data["longitude"],
            y=self.validated_data["latitude"],
            srid=4326,
        )
        provider.save(update_fields=["location", "updated_at"])


# ── Self-Service Onboarding Serializers ───────────────────────────────────────


class OnboardingPersonalInfoSerializer(serializers.ModelSerializer):
    """
    PATCH /onboarding/personal/

    The provider fills in professional + location details.
    Identity fields (first_name, last_name, email, phone) are read from the
    authenticated provider account — the provider set them during registration.
    """

    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    phone = serializers.CharField(read_only=True)

    class Meta:
        model = ProviderOnboarding
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "date_of_birth",
            "address",
            "region",
            "category",
            "hourly_rate",
            "years_of_experience",
            "bio",
        ]

    def validate_date_of_birth(self, value):
        today = timezone.now().date()
        age = (
            today.year
            - value.year
            - ((today.month, today.day) < (value.month, value.day))
        )
        if age < 18:
            raise serializers.ValidationError(
                "You must be 18 or older to register as a provider."
            )
        return value


class OnboardingDocumentsSerializer(serializers.ModelSerializer):
    """
    PATCH /onboarding/documents/

    Accepts file uploads for all required (and optional) documents.
    Extension and size limits are enforced by the model validators.
    Status eligibility is enforced by the view before this serializer runs.
    """

    class Meta:
        model = ProviderOnboarding
        fields = [
            "nid_front",
            "nid_back",
            "police_clearance_certificate",
            "professional_certificate",
            "profile_photo",
        ]


class OnboardingStatusSerializer(serializers.ModelSerializer):
    """
    GET /onboarding/status/

    Read-only view of the application state for the mobile app.
    """

    ai_report_summary = serializers.SerializerMethodField()
    can_resubmit = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProviderOnboarding
        fields = [
            "id",
            "status",
            "ai_validation_status",
            "ai_report_summary",
            "rejection_reason",
            "change_requests",
            "can_resubmit",
            "can_resubmit_after",
            "submitted_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_ai_report_summary(self, obj):
        report = obj.ai_validation_report
        if not report:
            return None
        return {
            "status": report.get("status"),
            "issues": report.get("issues", []),
            "overall_confidence": report.get("overall_confidence"),
        }
