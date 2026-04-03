from django.urls import path

from .views import (
    CustomerCancelView,
    CustomerRateProviderView,
    HistoryDetailView,
    ProviderAcceptView,
    ProviderCancelView,
    ProviderCompleteView,
    ProviderDeclineView,
    ProviderIncomingRequestsView,
    ProviderOpenRequestsView,
    ProviderPickRequestView,
    ProviderStartView,
    ServiceRequestDetailView,
    ServiceRequestListView,
)

app_name = "bookings"

urlpatterns = [
    # ── Unified list + create ─────────────────────────────────
    path("requests/", ServiceRequestListView.as_view(), name="request-list-create"),
    # ── Unified detail ────────────────────────────────────────
    path(
        "requests/<uuid:pk>/", ServiceRequestDetailView.as_view(), name="request-detail"
    ),
    # ── Customer actions ──────────────────────────────────────
    path(
        "requests/<uuid:pk>/cancel/",
        CustomerCancelView.as_view(),
        name="request-cancel",
    ),
    path(
        "requests/<uuid:pk>/rate/",
        CustomerRateProviderView.as_view(),
        name="request-rate",
    ),
    # ── Provider: pool + self-assign ──────────────────────────
    path(
        "requests/open/", ProviderOpenRequestsView.as_view(), name="request-open-pool"
    ),
    path(
        "requests/incoming/",
        ProviderIncomingRequestsView.as_view(),
        name="request-incoming",
    ),
    path(
        "requests/<uuid:pk>/pick/",
        ProviderPickRequestView.as_view(),
        name="request-pick",
    ),
    # ── Provider: FSM actions ─────────────────────────────────
    path(
        "requests/<uuid:pk>/accept/",
        ProviderAcceptView.as_view(),
        name="request-accept",
    ),
    path(
        "requests/<uuid:pk>/decline/",
        ProviderDeclineView.as_view(),
        name="request-decline",
    ),
    path(
        "requests/<uuid:pk>/start/", ProviderStartView.as_view(), name="request-start"
    ),
    path(
        "requests/<uuid:pk>/complete/",
        ProviderCompleteView.as_view(),
        name="request-complete",
    ),
    path(
        "requests/<uuid:pk>/provider-cancel/",
        ProviderCancelView.as_view(),
        name="request-provider-cancel",
    ),
    # ── Unified history detail ────────────────────────────────
    path("history/<uuid:pk>/", HistoryDetailView.as_view(), name="history-detail"),
]
