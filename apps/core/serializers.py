from rest_framework import serializers

from .models import Category, Region


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = [
            'id', 'name', 'slug', 'description',
            'icon', 'order', 'is_active',
        ]


class RegionSerializer(serializers.ModelSerializer):
    latitude = serializers.FloatField(
        source='location.y', read_only=True, default=None)
    longitude = serializers.FloatField(
        source='location.x', read_only=True, default=None)

    class Meta:
        model = Region
        fields = [
            'id', 'name', 'slug', 'code',
            'country', 'latitude', 'longitude', 'is_active',
        ]
