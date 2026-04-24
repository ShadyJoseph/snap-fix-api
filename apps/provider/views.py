from django.db import IntegrityError, transaction
from knox.models import AuthToken
from knox.views import LogoutView as KnoxLogoutView
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .choices import AIValidationStatus, OnboardingStatus
from .models import ProviderOnboarding
from .permissions import IsAwaitingOnboarding
from .serializers import (
    OnboardingDocumentsSerializer,
    OnboardingPersonalInfoSerializer,
    OnboardingStatusSerializer,
    ProviderLocationSerializer,
    ProviderLoginSerializer,
    ProviderProfileSerializer,
    ProviderRegisterSerializer,
    ProviderSerializer,
    ProviderUpdateSerializer,
)
from .tasks import validate_onboarding_documents


class ProviderRegisterView(generics.CreateAPIView):
    """
    POST /api/v1/providers/register/

    Creates a Provider account with the password the provider sets here.
    Issues an onboarding_token which the provider uses to complete their
    application via the self-service endpoints. Full login access is blocked
    until staff verify documents and approve the application.
    """

    serializer_class = ProviderRegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = serializer.save()
        _, token = AuthToken.objects.create(provider)
        return Response(
            {
                "message": (
                    "Registration successful. Use the onboarding_token to complete "
                    "your profile. You will receive full access once your application is approved."
                ),
                "onboarding_token": token,
                "next_step": "Submit your personal info at /api/v1/providers/onboarding/personal/",
            },
            status=status.HTTP_201_CREATED,
        )


class ProviderLoginView(generics.GenericAPIView):
    """
    POST /api/v1/providers/login/

    Only succeeds if:
      - credentials are valid
      - is_active=True  (set by staff on approval)
      - verification_status=verified
    """

    serializer_class = ProviderLoginSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        _, token = AuthToken.objects.create(user)
        return Response(
            {
                "provider": ProviderSerializer(user.provider).data,
                "token": token,
            }
        )


class ProviderLogoutView(KnoxLogoutView):
    """POST /api/v1/providers/logout/"""

    permission_classes = [permissions.IsAuthenticated]


class ProviderProfileView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/providers/me/"""

    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]
    serializer_class = ProviderProfileSerializer

    def get_object(self):
        if not hasattr(self.request.user, "provider"):
            raise PermissionDenied("No provider account found.")
        return self.request.user.provider

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = ProviderUpdateSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ProviderProfileSerializer(instance).data)


class ProviderLocationView(APIView):
    """
    PATCH /api/v1/providers/me/location/

    Lightweight ping endpoint — called by the provider app every ~60 s
    while they are on an active job.  Only updates the stored Point; no
    other profile fields are touched.
    """

    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request):
        if not hasattr(request.user, "provider"):
            raise PermissionDenied("No provider account found.")
        serializer = ProviderLocationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(provider=request.user.provider)
        return Response(
            {
                "latitude": serializer.validated_data["latitude"],
                "longitude": serializer.validated_data["longitude"],
            }
        )


# ── Self-Service Onboarding Views ─────────────────────────────────────────────


class OnboardingStatusView(generics.RetrieveAPIView):
    """
    GET /api/v1/providers/onboarding/status/

    Returns the provider's current onboarding application state.
    Accessible to any authenticated provider (active or inactive).
    Returns 404 if no application exists yet.
    """

    serializer_class = OnboardingStatusSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        if not hasattr(self.request.user, "provider"):
            raise PermissionDenied("No provider account found.")
        try:
            return ProviderOnboarding.objects.get(applicant=self.request.user.provider)
        except ProviderOnboarding.DoesNotExist:
            raise NotFound(
                "No onboarding application found. Start by submitting your personal info."
            ) from None


class OnboardingPersonalInfoView(APIView):
    """
    PATCH /api/v1/providers/onboarding/personal/

    Creates a DRAFT application if none exists, or updates an existing DRAFT /
    CHANGES_REQUIRED application with personal + professional details.

    If the provider had a previously rejected application and the 30-day
    cooldown has expired, calling this endpoint automatically resets it to DRAFT
    so they can reapply.
    """

    permission_classes = [IsAwaitingOnboarding]

    def patch(self, request):
        provider = request.user.provider

        # Fetch existing application; handle rejected + cooldown before anything else.
        try:
            onboarding = ProviderOnboarding.objects.get(applicant=provider)
        except ProviderOnboarding.DoesNotExist:
            onboarding = None

        if onboarding and onboarding.status == OnboardingStatus.REJECTED:
            if not onboarding.can_resubmit:
                resubmit_date = (
                    onboarding.can_resubmit_after.strftime("%Y-%m-%d")
                    if onboarding.can_resubmit_after
                    else "30 days from now"
                )
                return Response(
                    {
                        "detail": f"Your application was rejected. You may resubmit after {resubmit_date}.",
                        "can_resubmit_after": onboarding.can_resubmit_after,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            onboarding.resubmit()

        if onboarding and onboarding.status not in (
            OnboardingStatus.DRAFT,
            OnboardingStatus.CHANGES_REQUIRED,
        ):
            return Response(
                {
                    "detail": f"Cannot update personal info while application status is '{onboarding.status}'.",
                    "status": onboarding.status,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Identity fields always come from the authenticated provider account.
        identity = {
            "first_name": provider.first_name,
            "last_name": provider.last_name,
            "email": provider.email,
            "phone": provider.phone,
        }

        if onboarding is None:
            # First call — create a DRAFT. Use get_or_create to guard against
            # concurrent requests from the same provider (e.g. mobile retry).
            try:
                onboarding, _ = ProviderOnboarding.objects.get_or_create(
                    applicant=provider,
                    defaults={**identity, "status": OnboardingStatus.DRAFT},
                )
            except IntegrityError:
                # Extremely rare: race between get and create resolved here.
                onboarding = ProviderOnboarding.objects.get(applicant=provider)

        serializer = OnboardingPersonalInfoSerializer(
            onboarding, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(**identity)
        return Response(OnboardingStatusSerializer(instance).data)


class OnboardingDocumentsView(APIView):
    """
    PATCH /api/v1/providers/onboarding/documents/

    Upload or replace onboarding documents on an existing DRAFT or
    CHANGES_REQUIRED application. The application must exist — call
    /onboarding/personal/ first.
    """

    permission_classes = [IsAwaitingOnboarding]

    def patch(self, request):
        provider = request.user.provider
        try:
            onboarding = ProviderOnboarding.objects.get(applicant=provider)
        except ProviderOnboarding.DoesNotExist:
            return Response(
                {
                    "detail": "No onboarding application found. Submit personal info first."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if onboarding.status not in (
            OnboardingStatus.DRAFT,
            OnboardingStatus.CHANGES_REQUIRED,
        ):
            return Response(
                {
                    "detail": f"Cannot upload documents while application status is '{onboarding.status}'.",
                    "status": onboarding.status,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = OnboardingDocumentsSerializer(
            onboarding,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return Response(OnboardingStatusSerializer(instance).data)


class OnboardingSubmitView(APIView):
    """
    POST /api/v1/providers/onboarding/submit/

    Finalises a DRAFT application and submits it for review.

    Validates that all required documents are present, then:
      1. Sets status → PENDING
      2. Enqueues the AI validation Celery task
      3. Returns the updated application state
    """

    permission_classes = [IsAwaitingOnboarding]

    def post(self, request):
        provider = request.user.provider
        try:
            onboarding = ProviderOnboarding.objects.get(applicant=provider)
        except ProviderOnboarding.DoesNotExist:
            return Response(
                {
                    "detail": "No onboarding application found. Fill in your personal info and documents first."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if onboarding.status not in (
            OnboardingStatus.DRAFT,
            OnboardingStatus.CHANGES_REQUIRED,
        ):
            return Response(
                {
                    "detail": f"Application cannot be submitted from status '{onboarding.status}'.",
                    "status": onboarding.status,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Enforce completeness — these are nullable for the DRAFT stage only.
        missing = [
            field
            for field, value in [
                ("date_of_birth", onboarding.date_of_birth),
                ("address", onboarding.address),
                ("region", onboarding.region_id),
                ("category", onboarding.category_id),
                ("hourly_rate", onboarding.hourly_rate),
                ("nid_front", onboarding.nid_front),
                ("nid_back", onboarding.nid_back),
                (
                    "police_clearance_certificate",
                    onboarding.police_clearance_certificate,
                ),
            ]
            if not value
        ]
        if missing:
            raise ValidationError(
                {
                    "missing_fields": missing,
                    "detail": "Please complete all required fields before submitting.",
                }
            )

        onboarding.status = OnboardingStatus.PENDING
        onboarding.ai_validation_status = AIValidationStatus.PENDING
        onboarding.ai_validation_report = {}
        onboarding.save(
            update_fields=["status", "ai_validation_status", "ai_validation_report"]
        )

        # Enqueue after commit so the task never races against an uncommitted row.
        onboarding_id = str(onboarding.pk)
        transaction.on_commit(
            lambda: validate_onboarding_documents.delay(onboarding_id)
        )

        return Response(
            {
                "detail": "Application submitted successfully. We will review your documents and notify you of the decision.",
                "application": OnboardingStatusSerializer(onboarding).data,
            },
            status=status.HTTP_200_OK,
        )
