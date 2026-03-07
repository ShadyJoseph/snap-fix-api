from django.urls import path

from .views import CategoryListView, RegionListView

urlpatterns = [
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('regions/',    RegionListView.as_view(),    name='region-list'),
]
