from django.urls import path

from .views import (
    CategoryListView,
    NearestOfficeView,
    OfficeDetailView,
    OfficeListView,
    RegionListView,
)

app_name = "core"

urlpatterns = [
    path("categories/", CategoryListView.as_view(), name="category-list"),
    path("regions/", RegionListView.as_view(), name="region-list"),
    path("offices/", OfficeListView.as_view(), name="office-list"),
    # "nearest" must come before the UUID pattern to avoid matching as a UUID
    path("offices/nearest/", NearestOfficeView.as_view(), name="office-nearest"),
    path("offices/<uuid:id>/", OfficeDetailView.as_view(), name="office-detail"),
]
