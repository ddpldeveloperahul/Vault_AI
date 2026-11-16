from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from myapp.views import index_view

urlpatterns = [
    path("", index_view, name="home"),
    path("dashboard/", index_view, name="dashboard-home"),
    path("admin/", admin.site.urls),
    path("api/", include("myapp.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
