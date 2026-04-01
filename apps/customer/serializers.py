from django.contrib.auth import authenticate
from rest_framework import serializers

from .models import Customer


class CustomerRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = Customer
        fields = ["email", "first_name", "last_name", "phone", "password"]

    def create(self, validated_data):
        password = validated_data.pop("password")
        customer = Customer(**validated_data)
        customer.set_password(password)
        customer.save()
        return customer


class CustomerLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(email=data["email"], password=data["password"])
        if not user:
            raise serializers.ValidationError("Invalid credentials.")
        if not user.is_active:
            raise serializers.ValidationError("Account is disabled.")
        # ensure it's a customer
        if not hasattr(user, "customer"):
            raise serializers.ValidationError("No customer account found.")
        data["user"] = user
        return data


class CustomerSerializer(serializers.ModelSerializer):
    """Read-only serializer for returning customer data."""

    class Meta:
        model = Customer
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "phone",
            "wallet_balance",
            "total_bookings",
            "is_verified",
            "date_joined",
        ]
        read_only_fields = fields


class CustomerProfileSerializer(serializers.ModelSerializer):
    """Detailed serializer for the authenticated customer's own profile."""

    class Meta:
        model = Customer
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
            "wallet_balance",
            "total_cashback",
            "total_bookings",
            "is_verified",
            "date_joined",
        ]
        read_only_fields = fields


class CustomerUpdateSerializer(serializers.ModelSerializer):
    """PATCH /me/ — only non-sensitive profile fields."""

    class Meta:
        model = Customer
        fields = [
            "first_name",
            "last_name",
            "phone",
            "profile_picture",
            "address",
            "latitude",
            "longitude",
        ]
