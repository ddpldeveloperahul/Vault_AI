from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from myapp.models import ActivityLog, AppSetting, Job, Screenshot, User


@admin.register(User)
class UserAdmin(UserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "is_staff", "is_active")
    list_filter = ("is_staff", "is_superuser", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("JobVault AI Custom Fields", {"fields": ("role", "phone_number")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("JobVault AI Custom Fields", {"fields": ("email", "role", "phone_number")}),
    )


@admin.register(Screenshot)
class ScreenshotAdmin(admin.ModelAdmin):
    list_display = ("id", "original_name", "origin", "source_app", "stage", "created_at")
    list_filter = ("stage", "origin", "source_app", "created_at")
    search_fields = ("original_name", "filename", "raw_text")
    readonly_fields = ("created_at", "processed_at")


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "company", "location", "vault", "source_app", "status", "confidence")
    list_filter = ("status", "vault", "source_app", "work_mode")
    search_fields = ("title", "company", "location", "salary", "apply_contact")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AppSetting)
class AppSettingAdmin(admin.ModelAdmin):
    list_display = ("key",)
    search_fields = ("key",)


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "ip_address")
    list_filter = ("action", "created_at")
    search_fields = ("actor__username", "actor__email", "action", "details", "ip_address")
    readonly_fields = ("created_at",)
