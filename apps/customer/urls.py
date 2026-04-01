from django.urls import path

from .views import (
    CustomerFavoritesListView,
    CustomerFavoriteToggleView,
    CustomerLoginView,
    CustomerLogoutView,
    CustomerProfileView,
    CustomerRegisterView,
)

urlpatterns = [
    path("register/", CustomerRegisterView.as_view(), name="customer-register"),
    path("login/", CustomerLoginView.as_view(), name="customer-login"),
    path("logout/", CustomerLogoutView.as_view(), name="customer-logout"),
    path("me/", CustomerProfileView.as_view(), name="customer-profile"),
    path(
        "favorites/",
        CustomerFavoritesListView.as_view(),
        name="customer-favorites-list",
    ),
    path(
        "favorites/<uuid:provider_id>/toggle/",
        CustomerFavoriteToggleView.as_view(),
        name="customer-favorite-toggle",
    ),
]
