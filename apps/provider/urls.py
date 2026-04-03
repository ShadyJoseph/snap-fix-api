from django.urls import path

from .views import (
    ProviderLocationView,
    ProviderLoginView,
    ProviderLogoutView,
    ProviderProfileView,
    ProviderRegisterView,
)

app_name = "providers"

urlpatterns = [
    path("register/", ProviderRegisterView.as_view(), name="provider-register"),
    path("login/", ProviderLoginView.as_view(), name="provider-login"),
    path("logout/", ProviderLogoutView.as_view(), name="provider-logout"),
    path("me/", ProviderProfileView.as_view(), name="provider-profile"),
    path("me/location/", ProviderLocationView.as_view(), name="provider-location"),
]
