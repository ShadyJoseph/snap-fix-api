from django.urls import path

from .views import ProviderLoginView, ProviderLogoutView

urlpatterns = [
    path('login/',  ProviderLoginView.as_view(),  name='provider-login'),
    path('logout/', ProviderLogoutView.as_view(), name='provider-logout'),
]
