from django.urls import path

from .views import (
    CategoryListView,
    NearestOfficeView,
    OfficeDetailView,
    OfficeListView,
    RegionListView,
)

urlpatterns = [
    path("categories/", CategoryListView.as_view(), name="category-list"),
    path("regions/", RegionListView.as_view(), name="region-list"),
    path("offices/", OfficeListView.as_view(), name="office-list"),
    path("offices/nearest/", NearestOfficeView.as_view(), name="office-nearest"),
    path("offices/<uuid:id>/", OfficeDetailView.as_view(), name="office-detail"),
]
