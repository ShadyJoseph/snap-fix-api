from django.contrib.auth import authenticate
from django.contrib.gis.geos import Point
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

    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

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

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None


class CustomerUpdateSerializer(serializers.ModelSerializer):
    """PATCH /me/ — only non-sensitive profile fields."""

    latitude = serializers.FloatField(required=False, allow_null=True, write_only=True)
    longitude = serializers.FloatField(required=False, allow_null=True, write_only=True)

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
