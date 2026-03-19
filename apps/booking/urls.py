from django.urls import path

from .views import (
    CustomerCancelView,
    CustomerRequestDetailView,
    CustomerRequestListCreateView,
    ProviderAcceptView,
    ProviderCancelView,
    ProviderCompleteView,
    ProviderDeclineView,
    ProviderIncomingRequestsView,
    ProviderOpenRequestsView,
    ProviderPickRequestView,
    ProviderRequestListView,
    ProviderStartView,
)

# Customer
urlpatterns = [
    path(
        "requests/", CustomerRequestListCreateView.as_view(), name="request-list-create"
    ),
    path(
        "requests/<uuid:pk>/",
        CustomerRequestDetailView.as_view(),
        name="request-detail",
    ),
    path(
        "requests/<uuid:pk>/cancel/",
        CustomerCancelView.as_view(),
        name="request-cancel",
    ),
]

# Provider
urlpatterns += [
    path(
        "requests/incoming/",
        ProviderIncomingRequestsView.as_view(),
        name="request-incoming",
    ),
    path(
        "requests/my-jobs/", ProviderRequestListView.as_view(), name="request-my-jobs"
    ),
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
    path(
        "requests/open/",
        ProviderOpenRequestsView.as_view(),
        name="request-open-pool",
    ),
    path(
        "requests/<uuid:pk>/pick/",
        ProviderPickRequestView.as_view(),
        name="request-pick",
    ),
]
