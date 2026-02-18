from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path


def home(request):
    return HttpResponse(
        '<h1>Welcome to SnapFix</h1>'
        '<p><a href="/admin/">Go to Admin Panel</a></p>'
    )


urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
]

# Serve media and static files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,
                          document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL,
                          document_root=settings.STATIC_ROOT)
