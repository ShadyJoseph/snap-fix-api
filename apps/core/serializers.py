from rest_framework import serializers

from .models import Category, Office, Region


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "icon",
            "order",
            "is_active",
        ]


class RegionSerializer(serializers.ModelSerializer):
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    def get_latitude(self, obj):
        return obj.latitude

    def get_longitude(self, obj):
        return obj.longitude

    class Meta:
        model = Region
        fields = [
            "id",
            "name",
            "slug",
            "code",
            "country",
            "latitude",
            "longitude",
            "is_active",
        ]


class OfficeListSerializer(serializers.ModelSerializer):
    region_name = serializers.CharField(source="region.name", read_only=True)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    def get_latitude(self, obj):
        return obj.latitude

    def get_longitude(self, obj):
        return obj.longitude

    class Meta:
        model = Office
        fields = [
            "id",
            "name",
            "address",
            "landmark",
            "latitude",
            "longitude",
            "region_name",
            "working_hours",
        ]


class OfficeDetailSerializer(serializers.ModelSerializer):
    region = RegionSerializer(read_only=True)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    def get_latitude(self, obj):
        return obj.latitude

    def get_longitude(self, obj):
        return obj.longitude

    class Meta:
        model = Office
        fields = [
            "id",
            "name",
            "address",
            "landmark",
            "latitude",
            "longitude",
            "region",
            "working_hours",
            "is_active",
            "created_at",
        ]
