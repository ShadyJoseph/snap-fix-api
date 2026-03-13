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
        from apps.user.models import User

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
        auth_user = authenticate(email=data["email"], password=data["password"])
        if not auth_user or not isinstance(auth_user, User):
            raise serializers.ValidationError("Invalid credentials.")

        if not auth_user.is_active:
            raise serializers.ValidationError(
                "Your account is not active yet. Please visit our office to complete verification."
            )
        if not hasattr(auth_user, "provider"):
            raise serializers.ValidationError("No provider account found.")
        if (
            auth_user.provider.verification_status
            != ProviderVerificationStatus.VERIFIED
        ):  # type: ignore
            raise serializers.ValidationError("Provider account is not verified yet.")

        data["user"] = auth_user
        return data


class ProviderSerializer(serializers.ModelSerializer):
    """Minimal serializer — used on login response."""

    completion_rate = serializers.SerializerMethodField()

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
            "average_rating",
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
            "average_rating",
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
