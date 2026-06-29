from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse, JsonResponse
from django.urls import include, path, re_path
from django.views.static import serve

admin.site.site_header = "SnapFix Admin"
admin.site.site_title = "SnapFix"
admin.site.index_title = "Dashboard"


def home(request):
    html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SnapFix API</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: "Inter", system-ui, sans-serif;
      background: #F1F5F9;
      color: #0F172A;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 24px;
      -webkit-font-smoothing: antialiased;
    }
    .card {
      background: #fff;
      border: 1px solid #E2E8F0;
      border-radius: 20px;
      box-shadow: 0 8px 32px rgba(15,23,42,.10), 0 2px 8px rgba(15,23,42,.06);
      padding: 48px 48px 40px;
      width: 100%;
      max-width: 480px;
      text-align: center;
    }
    .logo {
      width: 80px;
      height: 80px;
      border-radius: 20px;
      display: block;
      margin: 0 auto 20px;
      box-shadow: 0 4px 16px rgba(37,99,235,.25);
    }
    .wordmark { font-size: 32px; font-weight: 800; letter-spacing: -1px; line-height: 1; margin-bottom: 6px; }
    .wordmark .snap { color: #1E3A8A; }
    .wordmark .fix  { color: #2563EB; }
    .tagline { font-size: 13px; font-weight: 500; color: #64748B; letter-spacing: 2px; text-transform: uppercase; margin-bottom: 32px; }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: #D1FAE5;
      color: #065F46;
      border-radius: 9999px;
      padding: 6px 16px;
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 32px;
    }
    .dot {
      width: 8px; height: 8px;
      background: #10B981;
      border-radius: 50%;
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50%       { opacity: .4; }
    }
    .divider { border: none; border-top: 1px solid #E2E8F0; margin: 0 0 28px; }
    .links { display: flex; flex-direction: column; gap: 10px; }
    .btn {
      display: block;
      padding: 12px 20px;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 600;
      text-decoration: none;
      transition: transform .12s, box-shadow .15s;
    }
    .btn:hover { transform: translateY(-1px); }
    .btn-primary {
      background: linear-gradient(135deg, #2563EB 0%, #1E3A8A 100%);
      color: #fff;
      box-shadow: 0 3px 12px rgba(37,99,235,.35);
    }
    .btn-primary:hover { box-shadow: 0 6px 20px rgba(37,99,235,.45); }
    .btn-secondary {
      background: #F8FAFC;
      color: #334155;
      border: 1.5px solid #CBD5E1;
    }
    .btn-secondary:hover { background: #EFF6FF; border-color: #2563EB; color: #2563EB; }
    .meta { margin-top: 28px; font-size: 12px; color: #94A3B8; }
    .meta span { margin: 0 6px; }
  </style>
</head>
<body>
  <div class="card">
    <img src="/static/admin/img/logo.png" alt="SnapFix" class="logo">
    <div class="wordmark"><span class="snap">Snap</span><span class="fix">Fix</span></div>
    <div class="tagline">On-demand home services</div>
    <div class="status"><span class="dot"></span> API is live</div>
    <hr class="divider">
    <div class="links">
      <a href="/admin/" class="btn btn-primary">Admin Dashboard</a>
    </div>
    <div class="meta">
      <span>REST API</span>&middot;<span>v1</span>&middot;<span>Django + DRF</span>
    </div>
  </div>
</body>
</html>"""
    return HttpResponse(html)


def api_root(request):
    base = request.build_absolute_uri("/api/v1/")
    return JsonResponse(
        {
            "status": "ok",
            "version": "v1",
            "endpoints": {
                "customers": base + "customers/",
                "providers": base + "providers/",
                "core": {
                    "categories": base + "core/categories/",
                    "regions": base + "core/regions/",
                    "offices": base + "core/offices/",
                },
                "bookings": base + "bookings/",
                "notifications": base + "notifications/",
            },
        }
    )


urlpatterns = [
    path("", home, name="home"),
    path("api/v1/", api_root, name="api-root"),
    path("admin/", admin.site.urls),
    path("api/v1/customers/", include("apps.customer.urls")),
    path("api/v1/providers/", include("apps.provider.urls")),
    path("api/v1/core/", include("apps.core.urls")),
    path("api/v1/bookings/", include("apps.booking.urls")),
    path("api/v1/notifications/", include("apps.notifications.urls")),
    # Serve uploaded media files from the Railway volume mounted at /app/media.
    re_path(r"^media/(?P<path>.+)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
