from django.contrib.auth import authenticate
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
            "date_joined",
        ]
        read_only_fields = fields

    def get_completion_rate(self, obj):
        return obj.get_completion_rate()


class ProviderProfileSerializer(serializers.ModelSerializer):
    """Full serializer for the authenticated provider's own profile (GET /me/)."""

    completion_rate = serializers.SerializerMethodField()
    rating = serializers.FloatField(read_only=True)

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
