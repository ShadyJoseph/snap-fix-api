import logging

from django.contrib.gis.db.models.functions import Distance
from django.db import transaction
from django.http import Http404
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications import service as notifications
from apps.provider.choices import ProviderVerificationStatus

from .choices import CancelledBy, PaymentMethod, ServiceRequestStatus
from .models import Review, ServiceRequest, ServiceRequestPhoto
from .serializers import (
    CustomerApproveQuoteSerializer,
    CustomerRequestDetailSerializer,
    DirectBookingCreateSerializer,
    InitiateCardPaymentSerializer,
    ProviderQuoteSerializer,
    ProviderRequestDetailSerializer,
    ReviewCreateSerializer,
    ReviewSerializer,
    ServiceRequestCancelSerializer,
    ServiceRequestCreateSerializer,
    ServiceRequestDeclineSerializer,
    ServiceRequestSerializer,
)

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def get_request_or_404(pk, queryset):
    try:
        return queryset.get(pk=pk)
    except ServiceRequest.DoesNotExist as e:
        raise Http404 from e


def fsm_transition(transition_fn):
    """Wrap FSM calls: ValueError → 400 ValidationError."""
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


def _sr_queryset_base():
    return ServiceRequest.objects.select_related(
        "category", "region", "customer", "provider", "review"
    ).prefetch_related("photos")


# ── List + Create ─────────────────────────────────────────────────────────────


class ServiceRequestListView(generics.ListCreateAPIView):
    """
    GET  — Customer: own requests. Provider: own jobs. Supports ?status= filter.
    POST — Customer only. Requires ≥1 photo (multipart, field: photos, max 5).
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ServiceRequestCreateSerializer
        return ServiceRequestSerializer

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, "customer"):
            qs = (
                ServiceRequest.objects.filter(customer=user.customer)
                .select_related("category", "region", "provider", "review")
                .prefetch_related("photos")
            )
        elif hasattr(user, "provider"):
            qs = (
                ServiceRequest.objects.filter(provider=user.provider)
                .select_related("category", "region", "customer", "provider", "review")
                .prefetch_related("photos")
            )
        else:
            return ServiceRequest.objects.none()

        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs.order_by("-created_at")

    def perform_create(self, serializer):
        customer = get_customer_or_403(self.request.user)
        photos = self.request.FILES.getlist("photos")
        if not photos:
            raise ValidationError({"photos": "At least one photo is required."})
        if len(photos) > 5:
            raise ValidationError({"photos": "Maximum 5 photos allowed."})
        sr = serializer.save(customer=customer)
        for photo in photos:
            ServiceRequestPhoto.objects.create(service_request=sr, image=photo)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        sr = _sr_queryset_base().get(pk=serializer.instance.pk)
        return Response(
            ServiceRequestSerializer(sr, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class ServiceRequestDetailView(generics.RetrieveAPIView):
    serializer_class = ServiceRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, "customer"):
            return (
                ServiceRequest.objects.filter(customer=user.customer)
                .select_related("category", "region", "provider", "review")
                .prefetch_related("photos")
            )
        if hasattr(user, "provider"):
            return (
                ServiceRequest.objects.filter(provider=user.provider)
                .select_related("category", "region", "customer", "provider", "review")
                .prefetch_related("photos")
            )
        return ServiceRequest.objects.none()


# ── Customer Actions ──────────────────────────────────────────────────────────


class CustomerCancelView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        customer = get_customer_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(customer=customer)
            .select_related("category", "region", "customer", "provider", "review")
            .prefetch_related("photos"),
        )
        serializer = ServiceRequestCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider_snapshot = sr.provider if sr.provider_id else None
        with transaction.atomic():
            fsm_transition(
                lambda: sr.cancel(
                    cancelled_by=CancelledBy.CUSTOMER,
                    reason=serializer.validated_data.get("reason", ""),
                )
            )
            sr = _sr_queryset_base().get(pk=sr.pk)
            if provider_snapshot:
                notifications.notify_provider_cancelled_by_customer(
                    sr, provider_snapshot
                )
        return Response(ServiceRequestSerializer(sr).data)


class DirectBookingView(APIView):
    """
    Customer creates a booking and directly assigns it to a specific favorite provider.

    The provider must be in the customer's favorites, be verified and available,
    offer the requested category, and not currently be handling another active job.

    The request is created in PENDING then immediately moved to ASSIGNED via the
    standard FSM assign() transition, bypassing the open pool. The provider can
    still quote, accept directly, or decline (which returns the request to PENDING).
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from django.core.exceptions import ObjectDoesNotExist

        customer = get_customer_or_403(request.user)

        serializer = DirectBookingCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        provider_id = serializer.validated_data.pop("provider_id")

        # Verify provider exists and is in the customer's favorites.
        try:
            provider = customer.favorite_providers.get(pk=provider_id)
        except ObjectDoesNotExist:
            raise ValidationError(
                {"provider_id": "Provider not found in your favorites."}
            ) from None

        if provider.verification_status != ProviderVerificationStatus.VERIFIED:
            raise ValidationError({"provider_id": "Provider is not verified."})

        category = serializer.validated_data.get("category")
        if not provider.categories.filter(pk=category.pk).exists():
            raise ValidationError(
                {"provider_id": "Provider does not offer this service category."}
            )

        photos = request.FILES.getlist("photos")
        if not photos:
            raise ValidationError({"photos": "At least one photo is required."})
        if len(photos) > 5:
            raise ValidationError({"photos": "Maximum 5 photos allowed."})

        active_statuses = [
            ServiceRequestStatus.ASSIGNED,
            ServiceRequestStatus.QUOTED,
            ServiceRequestStatus.CONFIRMED,
            ServiceRequestStatus.IN_PROGRESS,
        ]

        with transaction.atomic():
            # Re-fetch the provider under a row lock so the availability and
            # busy checks are race-free with concurrent direct booking requests.
            locked_provider = (
                customer.favorite_providers.select_for_update().get(pk=provider_id)
            )
            if not locked_provider.is_available:
                raise ValidationError({"provider_id": "Provider is currently unavailable."})
            if ServiceRequest.objects.filter(
                provider=locked_provider, status__in=active_statuses
            ).exists():
                raise ValidationError(
                    {"provider_id": "Provider is currently busy with another job."}
                )
            sr = serializer.save(customer=customer)
            for photo in photos:
                ServiceRequestPhoto.objects.create(service_request=sr, image=photo)
            fsm_transition(lambda: sr.assign(locked_provider))
            sr = _sr_queryset_base().get(pk=sr.pk)
            notifications.notify_provider_direct_request(sr)

        return Response(
            ServiceRequestSerializer(sr, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class CustomerApproveQuoteView(APIView):
    """
    Customer approves the provider's quoted price and confirms the payment split.

    Request body (all optional — defaults preserve original booking intent):
      {
        "wallet_amount": 50.00,   // how much to use from wallet (0 = none)
        "payment_method": "card"  // how to pay the remainder: cash | card | wallet
      }

    Rules:
      • payment_method = WALLET → wallet_amount must cover the full quoted price.
      • wallet_amount > 0 → wallet balance re-validated inside approve_quote()
        under a row lock (TOCTOU safe).
      • payment_method = CARD → a Stripe PaymentIntent is created for the card
        portion; customer must also call /initiate-card-payment/ with their
        Stripe PaymentMethod ID before the job completes.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        customer = get_customer_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(
                customer=customer, status=ServiceRequestStatus.QUOTED
            )
            .select_related("category", "region", "customer", "provider", "review")
            .prefetch_related("photos"),
        )

        serializer = CustomerApproveQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        wallet_amount = (
            serializer.validated_data.get("wallet_amount", sr.wallet_amount) or 0
        )
        payment_method = serializer.validated_data.get(
            "payment_method", sr.payment_method
        )

        # Enforce: WALLET method → wallet covers everything.
        if payment_method == PaymentMethod.WALLET:
            wallet_amount = sr.quoted_price  # will be validated in approve_quote()

        # Persist the (possibly updated) payment split before FSM transition.
        ServiceRequest.objects.filter(pk=sr.pk).update(
            wallet_amount=wallet_amount,
            payment_method=payment_method,
        )
        sr.refresh_from_db()

        with transaction.atomic():
            fsm_transition(sr.approve_quote)
            sr = _sr_queryset_base().get(pk=sr.pk)
            notifications.notify_provider_quote_approved(sr)
        return Response(ServiceRequestSerializer(sr).data)


class CustomerRejectQuoteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        customer = get_customer_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(
                customer=customer, status=ServiceRequestStatus.QUOTED
            )
            .select_related("category", "region", "customer", "provider", "review")
            .prefetch_related("photos"),
        )
        # Capture provider before reject_quote() clears sr.provider.
        provider_snapshot = sr.provider
        with transaction.atomic():
            fsm_transition(sr.reject_quote)
            sr = _sr_queryset_base().get(pk=sr.pk)
            if provider_snapshot:
                notifications.notify_provider_quote_rejected(sr, provider_snapshot)
        return Response(ServiceRequestSerializer(sr).data)


class InitiateCardPaymentView(APIView):
    """
    Customer attaches a Stripe PaymentMethod ID to the service request so the
    card can be charged when the job completes.

    Only valid when payment_method == CARD and card_amount > 0.
    Stores stripe_payment_method_id on the request; a PaymentIntent is created
    (but NOT captured) so the customer sees a pending charge on their card.

    Must be called after approving the quote and before the provider completes.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        import stripe
        from django.conf import settings

        customer = get_customer_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(
                customer=customer,
                status__in=[
                    ServiceRequestStatus.CONFIRMED,
                    ServiceRequestStatus.IN_PROGRESS,
                ],
            )
            .select_related("category", "region", "provider", "review")
            .prefetch_related("photos"),
        )

        if sr.payment_method != PaymentMethod.CARD:
            raise ValidationError(
                "Card payment initiation is only required when payment method is CARD."
            )

        card_amount = sr.card_amount
        if not card_amount or card_amount <= 0:
            raise ValidationError(
                "No card amount to charge — wallet covers the full price."
            )

        serializer = InitiateCardPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        stripe_pm_id = serializer.validated_data["stripe_payment_method_id"]
        return_url = serializer.validated_data["return_url"]

        stripe.api_key = settings.STRIPE_SECRET_KEY

        try:
            # Create a manual-capture PaymentIntent.
            # We capture it at complete() so money only moves when service is done.
            intent = stripe.PaymentIntent.create(
                amount=int(card_amount * 100),
                currency=settings.STRIPE_CURRENCY,
                payment_method=stripe_pm_id,
                capture_method="manual",
                confirm=True,
                return_url=return_url,
                metadata={"service_request_id": str(sr.id)},
            )
        except stripe.error.StripeError as exc:
            raise ValidationError(f"Stripe error: {exc.user_message}") from exc

        # Persist both IDs for use at completion.
        ServiceRequest.objects.filter(pk=sr.pk).update(
            stripe_payment_intent_id=intent.id,
        )
        # Also persist the payment method ID so complete() can use it if needed.
        # We store it in a transient attribute (not a DB field) for the response,
        # and rely on the PaymentIntent ID for actual capture.
        sr.refresh_from_db()
        return Response(
            {
                **ServiceRequestSerializer(sr).data,
                "stripe_client_secret": intent.client_secret,
            }
        )


# ── Provider Actions ──────────────────────────────────────────────────────────


class ProviderIncomingRequestsView(generics.ListAPIView):
    serializer_class = ServiceRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        provider = get_provider_or_403(self.request.user)
        return (
            ServiceRequest.objects.filter(
                provider=provider, status=ServiceRequestStatus.ASSIGNED
            )
            .select_related("category", "region", "customer", "provider", "review")
            .prefetch_related("photos")
            .order_by("-assigned_at")
        )


class ProviderQuoteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        provider = get_provider_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(
                provider=provider, status=ServiceRequestStatus.ASSIGNED
            )
            .select_related("category", "region", "customer", "provider", "review")
            .prefetch_related("photos"),
        )
        serializer = ProviderQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            fsm_transition(lambda: sr.quote(serializer.validated_data["price"]))
            sr = _sr_queryset_base().get(pk=sr.pk)
            notifications.notify_customer_quote_received(sr)
        return Response(ServiceRequestSerializer(sr).data)


class ProviderAcceptView(APIView):
    """Provider skips the quote step and accepts directly (assigned → confirmed)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        provider = get_provider_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(
                provider=provider, status=ServiceRequestStatus.ASSIGNED
            )
            .select_related("category", "region", "customer", "provider", "review")
            .prefetch_related("photos"),
        )
        with transaction.atomic():
            fsm_transition(sr.confirm)
            sr = _sr_queryset_base().get(pk=sr.pk)
            notifications.notify_customer_request_accepted(sr)
        return Response(ServiceRequestSerializer(sr).data)


class ProviderDeclineView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        provider = get_provider_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(provider=provider)
            .select_related("category", "region", "customer", "provider", "review")
            .prefetch_related("photos"),
        )
        serializer = ServiceRequestDeclineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            fsm_transition(
                lambda: sr.decline(reason=serializer.validated_data.get("reason", ""))
            )
            sr = _sr_queryset_base().get(pk=sr.pk)
            notifications.notify_customer_request_declined(sr)
        return Response(ServiceRequestSerializer(sr).data)


class ProviderStartView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        provider = get_provider_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(provider=provider)
            .select_related("category", "region", "customer", "provider", "review")
            .prefetch_related("photos"),
        )
        with transaction.atomic():
            fsm_transition(sr.start)
            sr = _sr_queryset_base().get(pk=sr.pk)
            notifications.notify_customer_job_started(sr)
        return Response(ServiceRequestSerializer(sr).data)


class ProviderCompleteView(APIView):
    """
    Provider marks the job done. Payment settled automatically:
      • Wallet portion deducted from customer balance (row-locked).
      • Card portion captured via Stripe (if payment_method == CARD).
      • Cash portion: honor-system, paid directly to provider.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        provider = get_provider_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(provider=provider)
            .select_related("category", "region", "customer", "provider", "review")
            .prefetch_related("photos"),
        )
        with transaction.atomic():
            fsm_transition(sr.complete)
            sr = _sr_queryset_base().get(pk=sr.pk)
            notifications.notify_customer_job_completed(sr)
            notifications.notify_provider_payment_settled(sr)
        return Response(ServiceRequestSerializer(sr).data)


class ProviderCancelView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        provider = get_provider_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(provider=provider)
            .select_related("category", "region", "customer", "provider", "review")
            .prefetch_related("photos"),
        )
        serializer = ServiceRequestCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            fsm_transition(
                lambda: sr.cancel(
                    cancelled_by=CancelledBy.PROVIDER,
                    reason=serializer.validated_data.get("reason", ""),
                )
            )
            sr = _sr_queryset_base().get(pk=sr.pk)
            notifications.notify_customer_cancelled_by_provider(sr)
        return Response(ServiceRequestSerializer(sr).data)


class ProviderPickRequestView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        provider = get_provider_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(
                status=ServiceRequestStatus.PENDING,
                category__in=provider.categories.all(),
            ),
        )
        with transaction.atomic():
            fsm_transition(lambda: sr.self_assign(provider))
            sr = _sr_queryset_base().get(pk=sr.pk)
            notifications.notify_customer_request_assigned(sr)
        return Response(ServiceRequestSerializer(sr).data)


class ProviderOpenRequestsView(generics.ListAPIView):
    serializer_class = ServiceRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        provider = get_provider_or_403(self.request.user)
        qs = (
            ServiceRequest.objects.filter(
                status=ServiceRequestStatus.PENDING,
                category__in=provider.categories.all(),
            )
            .select_related("category", "region")
            .prefetch_related("photos")
        )
        if provider.location:
            qs = qs.annotate(distance=Distance("location", provider.location)).order_by(
                "-is_urgent", "distance", "-created_at"
            )
        else:
            qs = qs.order_by("-is_urgent", "-created_at")
        return qs


# ── Rating ────────────────────────────────────────────────────────────────────


class CustomerRateProviderView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        customer = get_customer_or_403(request.user)
        sr = get_request_or_404(
            pk,
            ServiceRequest.objects.filter(customer=customer).select_related(
                "provider", "review"
            ),
        )

        if sr.status != ServiceRequestStatus.COMPLETED:
            raise ValidationError("You can only rate a completed request.")
        if not sr.provider_id:
            raise ValidationError("No provider associated with this request.")

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


# ── History Detail ────────────────────────────────────────────────────────────


class HistoryDetailView(generics.RetrieveAPIView):
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
            return (
                ServiceRequest.objects.filter(customer=user.customer)
                .select_related("category", "region", "provider", "review")
                .prefetch_related("photos")
            )
        if hasattr(user, "provider"):
            return (
                ServiceRequest.objects.filter(provider=user.provider)
                .select_related("category", "region", "customer", "provider", "review")
                .prefetch_related("photos")
            )
        return ServiceRequest.objects.none()
