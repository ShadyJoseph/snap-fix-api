from django.http import Http404
from knox.models import AuthToken
from knox.views import LogoutView as KnoxLogoutView
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.provider.models import Provider
from apps.provider.serializers import ProviderSerializer

from .serializers import (
    CustomerLoginSerializer,
    CustomerProfileSerializer,
    CustomerRegisterSerializer,
    CustomerSerializer,
    CustomerUpdateSerializer,
)


def get_customer_or_403(user):
    if not hasattr(user, "customer"):
        raise PermissionDenied("Only customers can access this endpoint.")
    return user.customer


class CustomerRegisterView(generics.CreateAPIView):
    """POST /api/customers/register/"""

    serializer_class = CustomerRegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = serializer.save()
        _, token = AuthToken.objects.create(customer)
        return Response(
            {
                "customer": CustomerSerializer(customer).data,
                "token": token,
            },
            status=status.HTTP_201_CREATED,
        )


class CustomerLoginView(generics.GenericAPIView):
    """POST /api/customers/login/"""

    serializer_class = CustomerLoginSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        _, token = AuthToken.objects.create(user)
        return Response(
            {
                "customer": CustomerSerializer(user.customer).data,
                "token": token,
            }
        )


class CustomerLogoutView(KnoxLogoutView):
    """POST /api/customers/logout/ — Knox handles token deletion."""

    permission_classes = [permissions.IsAuthenticated]


class CustomerProfileView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/customers/me/"""

    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]
    serializer_class = CustomerProfileSerializer

    def get_object(self):
        return get_customer_or_403(self.request.user)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = CustomerUpdateSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(CustomerProfileSerializer(instance).data)


# ── Favorites ─────────────────────────────────────────────────


class CustomerFavoriteToggleView(APIView):
    """
    POST /api/v1/customers/favorites/{provider_id}/toggle/

    Adds or removes a provider from the customer's favorites.
    Returns current state so the client knows which icon to show.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, provider_id):
        customer = get_customer_or_403(request.user)

        try:
            provider = Provider.objects.get(pk=provider_id)
        except Provider.DoesNotExist:
            raise Http404 from None

        if customer.favorite_providers.filter(pk=provider_id).exists():
            customer.favorite_providers.remove(provider)
            is_favorite = False
        else:
            customer.favorite_providers.add(provider)
            is_favorite = True

        return Response({"is_favorite": is_favorite, "provider_id": str(provider_id)})


class CustomerFavoritesListView(generics.ListAPIView):
    """
    GET /api/v1/customers/favorites/

    Returns the customer's favorited providers.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        return ProviderSerializer

    def get_queryset(self):
        customer = get_customer_or_403(self.request.user)
        return customer.favorite_providers.all()
