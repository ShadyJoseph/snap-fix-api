from django.urls import path

from .views import (
    ProviderLoginView,
    ProviderLogoutView,
    ProviderProfileView,
    ProviderRegisterView,
)

urlpatterns = [
    path("register/", ProviderRegisterView.as_view(), name="provider-register"),
    path("login/", ProviderLoginView.as_view(), name="provider-login"),
    path("logout/", ProviderLogoutView.as_view(), name="provider-logout"),
    path("me/", ProviderProfileView.as_view(), name="provider-profile"),
]
