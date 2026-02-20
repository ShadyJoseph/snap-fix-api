from django.urls import path

from .views import (
    CustomerLoginView,
    CustomerLogoutView,
    CustomerProfileView,
    CustomerRegisterView,
)

urlpatterns = [
    path('register/', CustomerRegisterView.as_view(), name='customer-register'),
    path('login/', CustomerLoginView.as_view(), name='customer-login'),
    path('logout/', CustomerLogoutView.as_view(), name='customer-logout'),
    path('me/', CustomerProfileView.as_view(),  name='customer-profile'),
]
