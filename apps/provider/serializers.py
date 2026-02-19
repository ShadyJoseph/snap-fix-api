from django.contrib.auth import authenticate
from rest_framework import serializers

from .models import Provider


class ProviderLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(email=data['email'], password=data['password'])
        if not user:
            raise serializers.ValidationError("Invalid credentials.")
        if not user.is_active:
            raise serializers.ValidationError("Account is disabled.")
        if not hasattr(user, 'provider'):
            raise serializers.ValidationError("No provider account found.")
        if not user.provider.verification_status == 'verified':
            raise serializers.ValidationError(
                "Provider account is not verified yet.")
        data['user'] = user
        return data


class ProviderSerializer(serializers.ModelSerializer):
    """Read-only serializer for returning provider data."""
    completion_rate = serializers.SerializerMethodField()

    class Meta:
        model = Provider
        fields = [
            'id', 'email', 'first_name', 'last_name',
            'phone', 'business_name', 'bio',
            'verification_status', 'is_available',
            'average_rating', 'total_reviews',
            'total_jobs', 'completed_jobs', 'completion_rate',
            'available_balance', 'total_earnings',
            'hourly_rate', 'years_of_experience',
            'date_joined',
        ]
        read_only_fields = fields

    def get_completion_rate(self, obj):
        return obj.get_completion_rate()
