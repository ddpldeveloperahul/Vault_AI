from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q
from rest_framework import serializers

from myapp.models import ActivityLog, AppSetting, Job, Screenshot

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "role_display",
            "phone_number",
            "is_active",
            "is_staff",
            "is_superuser",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "role",
            "role_display",
            "is_active",
            "is_staff",
            "is_superuser",
            "created_at",
            "updated_at",
        ]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={"input_type": "password"}
    )
    confirm_password = serializers.CharField(
        write_only=True,
        required=True,
        style={"input_type": "password"}
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "password",
            "confirm_password",
            "first_name",
            "last_name",
            "phone_number",
        ]
        read_only_fields = ["id"]
        extra_kwargs = {
            "first_name": {"required": False},
            "last_name": {"required": False},
            "phone_number": {"required": False},
        }

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value

    def validate(self, attrs):
        if attrs.get("password") != attrs.get("confirm_password"):
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        validated_data.pop("confirm_password")
        password = validated_data.pop("password")

        validated_data["role"] = User.Role.ADMIN
        validated_data["is_staff"] = True

        if not User.objects.exists():
            validated_data["is_superuser"] = True

        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


SignupSerializer = RegisterSerializer


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=False, write_only=True)
    email = serializers.EmailField(required=False, write_only=True)
    password = serializers.CharField(
        required=True,
        write_only=True,
        style={"input_type": "password"}
    )

    def validate(self, attrs):
        identifier = attrs.get("username") or attrs.get("email")
        password = attrs.get("password", "")

        if not identifier or not password:
            raise serializers.ValidationError("Both username/email and password are required.")

        identifier = str(identifier).strip()

        # Match user by username or email
        user = User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)
        ).first()

        if not user or not user.check_password(password):
            raise serializers.ValidationError("Invalid username or password.")

        if not user.is_active:
            raise serializers.ValidationError("This admin account is inactive.")

        attrs["user"] = user
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        validators=[validate_password]
    )
    confirm_new_password = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_new_password"]:
            raise serializers.ValidationError({"confirm_new_password": "New passwords do not match."})
        return attrs

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is not correct.")
        return value


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        val = value.strip().lower()
        user = User.objects.filter(Q(email__iexact=val) | Q(username__iexact=val)).first()
        if not user:
            raise serializers.ValidationError("No active user found with this email address or username.")
        if not user.is_active:
            raise serializers.ValidationError("This user account is currently inactive.")
        return val


class VerifyResetTokenSerializer(serializers.Serializer):
    uidb64 = serializers.CharField(required=False, allow_blank=True)
    token = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    otp = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        uidb64 = attrs.get("uidb64")
        token = attrs.get("token")
        email = attrs.get("email")
        otp = attrs.get("otp")

        if not (uidb64 and token) and not (email and otp):
            raise serializers.ValidationError("Either (uidb64 and token) or (email and otp) must be provided.")
        return attrs


class ResetPasswordSerializer(serializers.Serializer):
    uidb64 = serializers.CharField(required=False, allow_blank=True)
    token = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    otp = serializers.CharField(required=False, allow_blank=True)
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        validators=[validate_password],
        style={"input_type": "password"}
    )
    confirm_new_password = serializers.CharField(
        required=True,
        write_only=True,
        style={"input_type": "password"}
    )

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_new_password"]:
            raise serializers.ValidationError({"confirm_new_password": "New passwords do not match."})

        uidb64 = attrs.get("uidb64")
        token = attrs.get("token")
        email = attrs.get("email")
        otp = attrs.get("otp")

        if not (uidb64 and token) and not (email and otp):
            raise serializers.ValidationError("Either (uidb64 and token) or (email and otp) must be provided.")
        return attrs


class JobSimpleSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True)

    class Meta:
        model = Job
        fields = ["id", "code", "status"]


class ScreenshotSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    job_count = serializers.SerializerMethodField()
    jobs = serializers.SerializerMethodField()
    error = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)

    class Meta:
        model = Screenshot
        fields = [
            "id",
            "filename",
            "original_name",
            "size",
            "image",
            "origin",
            "source_app",
            "stage",
            "error",
            "raw_text",
            "job_count",
            "created_at",
            "processed_at",
            "jobs",
        ]

    def get_image(self, obj):
        if obj.file:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.file.url)
            return obj.file.url
        return None

    def get_job_count(self, obj):
        return obj.jobs.count()

    def get_jobs(self, obj):
        return JobSimpleSerializer(obj.jobs.all(), many=True).data

    def get_error(self, obj):
        if not obj.error:
            return None
        from myapp.utils import sanitize_ai_error
        return sanitize_ai_error(obj.error)


class JobSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True)
    experience = serializers.CharField(read_only=True)
    screenshot_id = serializers.IntegerField(source="screenshot.id", read_only=True)
    image = serializers.SerializerMethodField()
    original_name = serializers.CharField(source="screenshot.original_name", read_only=True)
    filename = serializers.CharField(source="screenshot.filename", read_only=True)
    raw_text = serializers.CharField(source="screenshot.raw_text", read_only=True)
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    updated_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    vaults = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [
            "id",
            "code",
            "job_id",
            "screenshot_id",
            "title",
            "sector",
            "company",
            "location",
            "country",
            "exp_min",
            "exp_max",
            "experience",
            "salary",
            "qualification",
            "other_details",
            "work_mode",
            "apply_contact",
            "source_app",
            "vault",
            "vaults",
            "confidence",
            "evidence",
            "flags",
            "status",
            "duplicate_of",
            "fingerprint",
            "created_at",
            "updated_at",
            "image",
            "original_name",
            "filename",
            "raw_text",
        ]

    def get_vaults(self, obj):
        v = str(obj.vault or "")
        return [x.strip() for x in v.split(",") if x.strip()]

    def get_image(self, obj):
        if obj.screenshot and obj.screenshot.file:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.screenshot.file.url)
            return obj.screenshot.file.url
        return None


class ActivityLogSerializer(serializers.ModelSerializer):
    at = serializers.DateTimeField(source="created_at", format="%Y-%m-%d %H:%M:%S", read_only=True)
    message = serializers.CharField(source="details", read_only=True)
    actor = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = ["id", "at", "actor", "message"]

    def get_actor(self, obj):
        return obj.actor.username if obj.actor else obj.action