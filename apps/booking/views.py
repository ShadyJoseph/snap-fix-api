import logging

from django.http import Http404
from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .choices import CancelledBy, ServiceRequestStatus
from .models import ServiceRequest
from .serializers import (
    ServiceRequestCancelSerializer,
    ServiceRequestCompleteSerializer,
    ServiceRequestCreateSerializer,
    ServiceRequestDeclineSerializer,
    ServiceRequestSerializer,
)

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────


def get_request_or_404(pk, queryset):
    try:
        return queryset.get(pk=pk)
    except ServiceRequest.DoesNotExist as e:
        raise Http404 from e


def fsm_transition(transition_fn):
    """Wrap a FSM transition and convert ValueError to ValidationError."""
    try:
        transition_fn()
    except ValueError as e:
        raise ValidationError(str(e)) from e


# ── Customer Views ───────────────────────────────────────────


class CustomerRequestListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/bookings/requests/   — customer's own requests
    POST /api/v1/bookings/requests/   — create a new request
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ServiceRequestCreateSerializer
        return ServiceRequestSerializer

    def get_queryset(self):
        return (
            ServiceRequest.objects.filter(customer=self.request.user.customer)
            .select_related("category", "region", "provider")
            .order_by("-created_at")
        )


class CustomerRequestDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/bookings/requests/{id}/
    """

    serializer_class = ServiceRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ServiceRequest.objects.filter(
            customer=self.request.user.customer
        ).select_related("category", "region", "provider")


class CustomerCancelView(APIView):
    """
    POST /api/v1/bookings/requests/{id}/cancel/
    Customer can cancel any non-terminal request.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(customer=request.user.customer),
        )
        serializer = ServiceRequestCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        fsm_transition(
            lambda: sr.cancel(
                cancelled_by=CancelledBy.CUSTOMER,
                reason=serializer.validated_data.get("reason", ""),
            )
        )

        return Response(ServiceRequestSerializer(sr).data)


# ── Provider Views ───────────────────────────────────────────


class ProviderIncomingRequestsView(generics.ListAPIView):
    """
    GET /api/v1/bookings/requests/incoming/
    Requests assigned to the provider — awaiting accept or decline.
    """

    serializer_class = ServiceRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            ServiceRequest.objects.filter(
                provider=self.request.user.provider,
                status=ServiceRequestStatus.ASSIGNED,
            )
            .select_related("category", "region", "customer")
            .order_by("-assigned_at")
        )


class ProviderRequestListView(generics.ListAPIView):
    """
    GET /api/v1/bookings/requests/my-jobs/
    All provider jobs across all statuses.
    """

    serializer_class = ServiceRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            ServiceRequest.objects.filter(provider=self.request.user.provider)
            .select_related("category", "region", "customer")
            .order_by("-created_at")
        )


class ProviderAcceptView(APIView):
    """
    POST /api/v1/bookings/requests/{id}/accept/
    Provider accepts the assignment → confirmed.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(provider=request.user.provider),
        )
        fsm_transition(sr.confirm)
        return Response(ServiceRequestSerializer(sr).data)


class ProviderDeclineView(APIView):
    """
    POST /api/v1/bookings/requests/{id}/decline/
    Provider declines → request goes back to pending for admin to reassign.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(provider=request.user.provider),
        )
        serializer = ServiceRequestDeclineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        fsm_transition(
            lambda: sr.decline(
                reason=serializer.validated_data.get("reason", ""),
            )
        )

        return Response(ServiceRequestSerializer(sr).data)


class ProviderStartView(APIView):
    """
    POST /api/v1/bookings/requests/{id}/start/
    Provider starts work → in_progress.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(provider=request.user.provider),
        )
        fsm_transition(sr.start)
        return Response(ServiceRequestSerializer(sr).data)


class ProviderCompleteView(APIView):
    """
    POST /api/v1/bookings/requests/{id}/complete/
    Provider completes the job, optionally submitting the final price.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(provider=request.user.provider),
        )
        serializer = ServiceRequestCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        fsm_transition(
            lambda: sr.complete(
                final_price=serializer.validated_data.get("final_price"),
            )
        )

        return Response(ServiceRequestSerializer(sr).data)


class ProviderCancelView(APIView):
    """
    POST /api/v1/bookings/requests/{id}/provider-cancel/
    Provider cancels → request cancelled, job count rolled back.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(provider=request.user.provider),
        )
        serializer = ServiceRequestCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        fsm_transition(
            lambda: sr.cancel(
                cancelled_by=CancelledBy.PROVIDER,
                reason=serializer.validated_data.get("reason", ""),
            )
        )

        return Response(ServiceRequestSerializer(sr).data)
