from knox.models import AuthToken
from knox.views import LogoutView as KnoxLogoutView
from rest_framework import generics, permissions
from rest_framework.response import Response

from .serializers import ProviderLoginSerializer, ProviderSerializer


class ProviderLoginView(generics.GenericAPIView):
    """POST /api/v1/providers/login/"""
    serializer_class = ProviderLoginSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        _, token = AuthToken.objects.create(user)
        return Response({
            'provider': ProviderSerializer(user.provider).data,
            'token': token,
        })


class ProviderLogoutView(KnoxLogoutView):
    """POST /api/v1/providers/logout/"""
    permission_classes = [permissions.IsAuthenticated]
