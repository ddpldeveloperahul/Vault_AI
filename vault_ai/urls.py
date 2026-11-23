from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from myapp.views import index_view, forgot_password_view

urlpatterns = [
    path("", index_view, name="index"),
    path("", index_view, name="home"),
    path("dashboard/", index_view, name="dashboard"),
    path("dashboard/", index_view, name="dashboard-home"),
    path("inbox/", index_view, name="inbox"),
    path("job/", index_view, name="job"),
    path("jobs/", index_view, name="jobs"),
    path("vault/", index_view, name="vault"),
    path("vaults/", index_view, name="vaults"),
    path("review/", index_view, name="review"),
    path("reviews/", index_view, name="reviews"),
    path("rules/", index_view, name="rules"),
    path("columns/", index_view, name="columns"),
    path("ai/", index_view, name="ai"),
    path("integrations/", index_view, name="integrations"),
    path("activity/", index_view, name="activity"),
    path("login/", index_view, name="login-page"),
    path("login", index_view),
    path("forgot-password/", forgot_password_view, name="forgot-password-ui"),
    path("forgot-password", forgot_password_view),
    path("reset-password/", forgot_password_view, name="reset-password-ui"),
    path("reset-password", forgot_password_view),
    path("admin/", admin.site.urls),
    path("api/", include("myapp.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
