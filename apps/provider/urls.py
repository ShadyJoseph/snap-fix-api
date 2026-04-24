from django.urls import path

from .views import (
    OnboardingDocumentsView,
    OnboardingPersonalInfoView,
    OnboardingStatusView,
    OnboardingSubmitView,
    ProviderLocationView,
    ProviderLoginView,
    ProviderLogoutView,
    ProviderProfileView,
    ProviderRegisterView,
)

app_name = "providers"

urlpatterns = [
    # Auth
    path("register/", ProviderRegisterView.as_view(), name="provider-register"),
    path("login/", ProviderLoginView.as_view(), name="provider-login"),
    path("logout/", ProviderLogoutView.as_view(), name="provider-logout"),
    # Profile
    path("me/", ProviderProfileView.as_view(), name="provider-profile"),
    path("me/location/", ProviderLocationView.as_view(), name="provider-location"),
    # Self-service onboarding
    path(
        "onboarding/status/", OnboardingStatusView.as_view(), name="onboarding-status"
    ),
    path(
        "onboarding/personal/",
        OnboardingPersonalInfoView.as_view(),
        name="onboarding-personal",
    ),
    path(
        "onboarding/documents/",
        OnboardingDocumentsView.as_view(),
        name="onboarding-documents",
    ),
    path(
        "onboarding/submit/", OnboardingSubmitView.as_view(), name="onboarding-submit"
    ),
]
