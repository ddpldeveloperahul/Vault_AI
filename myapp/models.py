from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"

    email = models.EmailField(unique=True, verbose_name="Email Address")
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.ADMIN,
        verbose_name="User Role"
    )
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="Phone Number"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    REQUIRED_FIELDS = ["email"]

    def __str__(self):
        return f"{self.username} (Admin)"

    @property
    def is_admin(self):
        return True

    def save(self, *args, **kwargs):
        self.role = self.Role.ADMIN
        self.is_staff = True
        super().save(*args, **kwargs)


class Screenshot(models.Model):
    STAGE_CHOICES = [
        ("received", "Received"),
        ("reading", "Reading"),
        ("verifying", "Verifying"),
        ("sorting", "Sorting"),
        ("saved", "Saved"),
        ("failed", "Failed"),
    ]

    file = models.FileField(upload_to="screenshots/", null=True, blank=True)
    filename = models.CharField(max_length=255)
    original_name = models.CharField(max_length=255)
    size = models.BigIntegerField(default=0)
    origin = models.CharField(max_length=50, default="upload")
    source_app = models.CharField(max_length=50, null=True, blank=True)
    stage = models.CharField(max_length=50, choices=STAGE_CHOICES, default="saved")
    error = models.TextField(null=True, blank=True)
    raw_text = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.original_name or f"Screenshot #{self.id}"


class Job(models.Model):
    STATUS_CHOICES = [
        ("synced", "In Sheet"),
        ("review", "Needs Review"),
        ("duplicate", "Duplicate"),
        ("rejected", "Rejected"),
    ]

    screenshot = models.ForeignKey(
        Screenshot,
        on_delete=models.CASCADE,
        related_name="jobs",
        null=True,
        blank=True
    )
    job_id = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    sector = models.CharField(max_length=255, null=True, blank=True)
    company = models.CharField(max_length=255, null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    exp_min = models.FloatField(null=True, blank=True)
    exp_max = models.FloatField(null=True, blank=True)
    salary = models.CharField(max_length=255, null=True, blank=True)
    qualification = models.TextField(null=True, blank=True)
    other_details = models.TextField(null=True, blank=True)
    work_mode = models.CharField(max_length=50, null=True, blank=True)
    apply_contact = models.CharField(max_length=255, null=True, blank=True)
    source_app = models.CharField(max_length=50, default="Other")
    vault = models.CharField(max_length=255, default="India · Fresher")
    confidence = models.FloatField(default=0.90)
    evidence = models.JSONField(default=dict, blank=True)
    flags = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="review")
    duplicate_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="duplicates"
    )
    fingerprint = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.code}: {self.title or 'Untitled'} ({self.company or 'Unknown'})"

    @property
    def code(self):
        return self.job_id or f"JV-{self.id}"

    @property
    def experience(self):
        if self.exp_min is None and self.exp_max is None:
            return ""
        if self.exp_min == 0 and self.exp_max is None:
            return "Fresher"
        if self.exp_max is None:
            return f"{int(self.exp_min) if self.exp_min.is_integer() else self.exp_min}+ yrs"
        min_v = int(self.exp_min) if self.exp_min and self.exp_min.is_integer() else (self.exp_min or 0)
        max_v = int(self.exp_max) if self.exp_max and self.exp_max.is_integer() else self.exp_max
        return f"{min_v}–{max_v} yrs"


class AppSetting(models.Model):
    key = models.CharField(max_length=50, unique=True)
    value = models.JSONField()

    def __str__(self):
        return self.key


class ActivityLog(models.Model):
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs"
    )
    action = models.CharField(max_length=100, verbose_name="Action")
    details = models.TextField(blank=True, null=True, verbose_name="Details")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP Address")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Activity Log"
        verbose_name_plural = "Activity Logs"

    def __str__(self):
        actor_name = self.actor.username if self.actor else "System"
        return f"[{self.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {actor_name} - {self.action}"
