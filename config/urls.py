from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic import RedirectView
from django.templatetags.static import static as static_url

urlpatterns = [
    path("admin/", admin.site.urls),
    re_path(r"^favicon\.ico$", RedirectView.as_view(url=static_url("favicon.svg"), permanent=False)),
    path("", include("apps.accounts.urls")),
    path("", include("apps.monitor.urls")),
]
