import logging

from django.db import transaction
from django.http import Http404
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .choices import CancelledBy, ServiceRequestStatus
from .models import Review, ServiceRequest
from .serializers import (
    CustomerRequestDetailSerializer,
    ProviderRequestDetailSerializer,
    ReviewCreateSerializer,
    ReviewSerializer,
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


def get_customer_or_403(user):
    if not hasattr(user, "customer"):
        raise PermissionDenied("Only customers can access this endpoint.")
    return user.customer


def get_provider_or_403(user):
    if not hasattr(user, "provider"):
        raise PermissionDenied("Only providers can access this endpoint.")
    return user.provider


# ── Unified Request Views ─────────────────────────────────────


class ServiceRequestListView(generics.ListCreateAPIView):
    """
    GET  /api/v1/bookings/requests/
         Customer → their own requests.
         Provider → their own jobs.
         Both support ?status= filter.
    POST /api/v1/bookings/requests/  — customer only.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ServiceRequestCreateSerializer
        return ServiceRequestSerializer

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, "customer"):
            qs = ServiceRequest.objects.filter(customer=user.customer).select_related(
                "category", "region", "provider", "review"
            )
        elif hasattr(user, "provider"):
            qs = ServiceRequest.objects.filter(provider=user.provider).select_related(
                "category", "region", "customer", "review"
            )
        else:
            return ServiceRequest.objects.none()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs.order_by("-created_at")

    def perform_create(self, serializer):
        customer = get_customer_or_403(self.request.user)
        serializer.save(customer=customer)


class ServiceRequestDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/bookings/requests/<id>/
    Customer → scoped to their requests.
    Provider → scoped to their assigned jobs.
    """

    serializer_class = ServiceRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, "customer"):
            return ServiceRequest.objects.filter(customer=user.customer).select_related(
                "category", "region", "provider", "review"
            )
        if hasattr(user, "provider"):
            return ServiceRequest.objects.filter(provider=user.provider).select_related(
                "category", "region", "customer", "review"
            )
        return ServiceRequest.objects.none()


class CustomerCancelView(APIView):
    """
    POST /api/v1/bookings/requests/{id}/cancel/
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        customer = get_customer_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(customer=customer),
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


# ── Provider Views ────────────────────────────────────────────


class ProviderIncomingRequestsView(generics.ListAPIView):
    """
    GET /api/v1/bookings/requests/incoming/
    Requests assigned to the provider — awaiting accept or decline.
    """

    serializer_class = ServiceRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        provider = get_provider_or_403(self.request.user)
        return (
            ServiceRequest.objects.filter(
                provider=provider, status=ServiceRequestStatus.ASSIGNED
            )
            .select_related("category", "region", "customer")
            .order_by("-assigned_at")
        )


class ProviderAcceptView(APIView):
    """
    POST /api/v1/bookings/requests/{id}/accept/
    Provider accepts the assignment → confirmed.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        provider = get_provider_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(provider=provider),
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
        provider = get_provider_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(provider=provider),
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
        provider = get_provider_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(provider=provider),
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
        provider = get_provider_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(provider=provider),
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
        provider = get_provider_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(provider=provider),
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


class ProviderPickRequestView(APIView):
    """
    POST /api/v1/bookings/requests/{id}/pick/
    Provider self-assigns a pending request from the open pool.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        provider = get_provider_or_403(request.user)
        # Must be pending — no provider filter here since it's unassigned
        sr = get_request_or_404(
            pk, ServiceRequest.objects.filter(status=ServiceRequestStatus.PENDING)
        )
        fsm_transition(lambda: sr.self_assign(provider))
        return Response(ServiceRequestSerializer(sr).data)


class ProviderOpenRequestsView(generics.ListAPIView):
    """
    GET /api/v1/bookings/requests/open/
    Pool of pending requests visible to all providers.
    Providers use this to browse and pick a job.
    """

    serializer_class = ServiceRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        get_provider_or_403(self.request.user)
        return (
            ServiceRequest.objects.filter(status=ServiceRequestStatus.PENDING)
            .select_related("category", "region")
            .order_by("-is_urgent", "-created_at")  # urgent first
        )


# ── Rating ────────────────────────────────────────────────────


class CustomerRateProviderView(APIView):
    """
    POST /api/v1/bookings/requests/{id}/rate/

    Customer rates the provider after completion.
    Idempotent: returns existing review if already rated.
    Triggers provider.update_rating() atomically.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        customer = get_customer_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(customer=customer).select_related("provider"),
        )

        if sr.status != ServiceRequestStatus.COMPLETED:
            raise ValidationError("You can only rate a completed request.")
        if not sr.provider_id:
            raise ValidationError("No provider associated with this request.")

        # Idempotent — return existing review if already rated
        if hasattr(sr, "review"):
            return Response(ReviewSerializer(sr.review).data)

        serializer = ReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            review = Review.objects.create(
                service_request=sr,
                customer=customer,
                provider=sr.provider,
                rating=serializer.validated_data["rating"],
                comment=serializer.validated_data.get("comment", ""),
            )
            sr.provider.update_rating(review.rating)

        return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)


# ── Unified History Detail ────────────────────────────────────


class HistoryDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/bookings/history/<id>/

    Full detail — token role determines the serializer and ownership scope.
    Customer → provider card + is_favorite_provider + review.
    Provider → customer card + review.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        user = self.request.user
        if hasattr(user, "customer"):
            return CustomerRequestDetailSerializer
        if hasattr(user, "provider"):
            return ProviderRequestDetailSerializer
        raise PermissionDenied("Must be a customer or provider.")

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, "customer"):
            return ServiceRequest.objects.filter(customer=user.customer).select_related(
                "category", "region", "provider", "review"
            )
        if hasattr(user, "provider"):
            return ServiceRequest.objects.filter(provider=user.provider).select_related(
                "category", "region", "customer", "review"
            )
        return ServiceRequest.objects.none()
