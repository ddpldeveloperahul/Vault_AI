from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from myapp.views import (
    ActivityView,
    ChangePasswordView,
    ExportCsvView,
    ExportExcelView,
    ForgotPasswordView,
    HealthView,
    IntegrationsView,
    JobApproveView,
    JobDetailView,
    JobGenerateContentView,
    JobRejectView,
    JobRestoreView,
    JobsListView,
    LoginView,
    LogoutView,
    RegisterView,
    ResetPasswordConfirmView,
    RulesTestView,
    ScreenshotDetailView,
    ScreenshotRetryView,
    ScreenshotsView,
    SettingsAiView,
    SettingsColumnsView,
    SettingsRulesView,
    SettingsView,
    StatsView,
    UserProfileView,
    VaultDetailManageView,
    VaultsManageView,
    VerifyResetTokenView,
)

urlpatterns = [
    
    # Authentication
    path("login/", LoginView.as_view(), name="login-root"),
    path("login", LoginView.as_view()),

    path("auth/signup/", RegisterView.as_view(), name="auth-signup"),
    path("auth/signup", RegisterView.as_view()),

    path("auth/token/refresh", TokenRefreshView.as_view()),
    path("auth/me/", UserProfileView.as_view(), name="user-profile"),
    path("auth/me", UserProfileView.as_view()),
    
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),



    # System & Dashboard
    path("health/", HealthView.as_view(), name="health"),
    path("health", HealthView.as_view()),
    path("stats/", StatsView.as_view(), name="stats"),
    path("stats", StatsView.as_view()),
    path("activity/", ActivityView.as_view(), name="activity-api"),
    path("activity", ActivityView.as_view()),
    path("integrations/", IntegrationsView.as_view(), name="integrations-api"),
    path("integrations", IntegrationsView.as_view()),

    # Screenshots
    path("screenshots/", ScreenshotsView.as_view(), name="screenshots-list"),
    path("screenshots", ScreenshotsView.as_view()),
    path("screenshots/<int:pk>/retry/", ScreenshotRetryView.as_view(), name="screenshot-retry"),
    path("screenshots/<int:pk>/retry", ScreenshotRetryView.as_view()),
    path("screenshots/<int:pk>/", ScreenshotDetailView.as_view(), name="screenshot-detail"),
    path("screenshots/<int:pk>", ScreenshotDetailView.as_view()),

    # Jobs
    path("jobs/", JobsListView.as_view(), name="jobs-list"),
    path("jobs", JobsListView.as_view()),
    path("jobs/<int:pk>/", JobDetailView.as_view(), name="job-detail"),
    path("jobs/<int:pk>", JobDetailView.as_view()),
    path("jobs/<int:pk>/approve/", JobApproveView.as_view(), name="job-approve"),
    path("jobs/<int:pk>/approve", JobApproveView.as_view()),
    path("jobs/<int:pk>/reject/", JobRejectView.as_view(), name="job-reject"),
    path("jobs/<int:pk>/reject", JobRejectView.as_view()),
    path("jobs/<int:pk>/restore/", JobRestoreView.as_view(), name="job-restore"),
    path("jobs/<int:pk>/restore", JobRestoreView.as_view()),
    path("jobs/<int:pk>/generate-content/", JobGenerateContentView.as_view(), name="job-generate-content"),
    path("jobs/<int:pk>/generate-content", JobGenerateContentView.as_view()),

    # Vaults Management
    path("vaults/", VaultsManageView.as_view(), name="vaults-manage"),
    path("vaults", VaultsManageView.as_view()),
    path("vaults/<str:vault_name>/", VaultDetailManageView.as_view(), name="vault-detail-manage"),
    path("vaults/<str:vault_name>", VaultDetailManageView.as_view()),
    path("settings/vaults/", VaultsManageView.as_view(), name="settings-vaults"),
    path("settings/vaults", VaultsManageView.as_view()),

    # Settings
    path("settings/", SettingsView.as_view(), name="settings"),
    path("settings", SettingsView.as_view()),
    path("settings/ai/", SettingsAiView.as_view(), name="settings-ai"),
    path("settings/ai", SettingsAiView.as_view()),
    path("settings/rules/", SettingsRulesView.as_view(), name="settings-rules"),
    path("settings/rules", SettingsRulesView.as_view()),
    path("rules/test/", RulesTestView.as_view(), name="rules-test"),
    path("rules/test", RulesTestView.as_view()),
    path("settings/columns/", SettingsColumnsView.as_view(), name="settings-columns"),
    path("settings/columns", SettingsColumnsView.as_view()),

    # Export
    path("export.csv", ExportCsvView.as_view(), name="export-csv"),
    path("export.csv/", ExportCsvView.as_view()),
    path("export.xlsx", ExportExcelView.as_view(), name="export-xlsx"),
    path("export.xlsx/", ExportExcelView.as_view()),

    # Authentication
    path("login/", LoginView.as_view(), name="login-root"),
    path("login", LoginView.as_view()),
    path("auth/signup/", RegisterView.as_view(), name="auth-signup"),
    path("auth/signup", RegisterView.as_view()),
    path("auth/register/", RegisterView.as_view(), name="auth-register"),
    path("auth/register", RegisterView.as_view()),
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/login", LoginView.as_view()),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/token/refresh", TokenRefreshView.as_view()),
    path("auth/me/", UserProfileView.as_view(), name="user-profile"),
    path("auth/me", UserProfileView.as_view()),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/logout", LogoutView.as_view()),
    path("auth/change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("auth/change-password", ChangePasswordView.as_view()),
    path("auth/forgot-password/", ForgotPasswordView.as_view(), name="auth-forgot-password"),
    path("auth/forgot-password", ForgotPasswordView.as_view()),
    path("auth/verify-reset-token/", VerifyResetTokenView.as_view(), name="auth-verify-reset-token"),
    path("auth/verify-reset-token", VerifyResetTokenView.as_view()),
    path("auth/reset-password/", ResetPasswordConfirmView.as_view(), name="auth-reset-password"),
    path("auth/reset-password", ResetPasswordConfirmView.as_view()),
]
