from knox.models import AuthToken
from knox.views import LogoutView as KnoxLogoutView
from rest_framework import generics, permissions, status
from rest_framework.response import Response

from .serializers import (
    CustomerLoginSerializer,
    CustomerProfileSerializer,
    CustomerRegisterSerializer,
    CustomerSerializer,
)


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


class CustomerProfileView(generics.RetrieveAPIView):
    """GET /api/v1/customers/me/"""

    serializer_class = CustomerProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user.customer  # type: ignore
