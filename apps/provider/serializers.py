from django.contrib.auth import authenticate
from django.contrib.gis.geos import Point
from rest_framework import serializers

from apps.user.models import User

from .choices import ProviderVerificationStatus
from .models import Provider


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
        return Provider.objects.create_user(  # type: ignore
            **validated_data,
            password=password,
            is_active=False,
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
            raise serializers.ValidationError(
                "Your account is not active yet. Please visit our office to complete verification."
            )

        if not hasattr(user, "provider"):
            raise serializers.ValidationError("No provider account found.")

        if user.provider.verification_status != ProviderVerificationStatus.VERIFIED:
            raise serializers.ValidationError("Provider account is not verified yet.")

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
