from rest_framework import generics, permissions

from .models import Category, Region
from .serializers import CategorySerializer, RegionSerializer


class CategoryListView(generics.ListAPIView):
    """GET /api/v1/core/categories/"""

    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return Category.objects.filter(is_active=True)


class RegionListView(generics.ListAPIView):
    """GET /api/v1/core/regions/"""

    serializer_class = RegionSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return Region.objects.filter(is_active=True)
