from knox.models import AuthToken
from knox.views import LogoutView as KnoxLogoutView
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .serializers import (
    ProviderLoginSerializer,
    ProviderProfileSerializer,
    ProviderRegisterSerializer,
    ProviderSerializer,
)


class ProviderRegisterView(generics.CreateAPIView):
    """
    POST /api/v1/providers/register/

    Creates an inactive Provider account with the password the provider sets here.
    The provider must then visit the office — staff verify documents and approve.
    No token is issued since the account is inactive until approved.
    """

    serializer_class = ProviderRegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {
                "message": (
                    "Registration received. Please visit your nearest office to complete "
                    "your verification. You will be able to log in once approved."
                ),
                "next_step": "Visit /api/v1/core/offices/nearest/ to find the closest office to you.",
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


class ProviderProfileView(generics.RetrieveAPIView):
    """
    GET /api/v1/providers/me/

    Returns the full profile of the currently authenticated provider.
    """

    serializer_class = ProviderProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        if not hasattr(self.request.user, "provider"):
            raise PermissionDenied("No provider account found.")
        return self.request.user.provider
