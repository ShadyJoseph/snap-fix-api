from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path


def home(request):
    return HttpResponse(
        '<h1>Welcome to SnapFix</h1><p><a href="/admin/">Go to Admin Panel</a></p>'
    )


urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("api/v1/customers/", include("apps.customer.urls")),
    path("api/v1/providers/", include("apps.provider.urls")),
    path("api/v1/bookings/", include("apps.booking.urls")),
    path("api/v1/core/", include("apps.core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
