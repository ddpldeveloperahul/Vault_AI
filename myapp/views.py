import csv
import io
import os
import random
from datetime import timedelta
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from django.shortcuts import render
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from PIL import Image
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from myapp.models import ActivityLog, AppSetting, Job, Screenshot, User
from myapp.serializers import (
    ActivityLogSerializer,
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    JobSerializer,
    LoginSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
    ScreenshotSerializer,
    UserSerializer,
    VerifyResetTokenSerializer,
)
from myapp.utils import (
    PROMPT,
    classify_job,
    calculate_fingerprint,
    generate_job_id,
    get_ai_settings,
    get_columns_setting,
    get_required_fields,
    get_vault_definitions,
    get_vault_names,
    get_vault_rules,
    process_screenshot,
    set_setting,
)


def index_view(request):
    return render(request, "dashboard.html")


def forgot_password_view(request):
    return render(request, "forgot_password.html")


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


# ------------------ System & Health ------------------
class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"ok": True, "provider": "mock", "authRequired": False})


class StatsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)

        total_screenshots = Screenshot.objects.count()
        screenshots_week = Screenshot.objects.filter(created_at__gte=week_ago).count()
        in_sheet = Job.objects.filter(status="synced").count()
        added_today = Job.objects.filter(status="synced", created_at__gte=today_start).count()
        review_count = Job.objects.filter(status="review").count()
        duplicates_count = Job.objects.filter(status="duplicate").count()
        failed_count = Screenshot.objects.filter(stage="failed").count()
        processing_count = Screenshot.objects.exclude(stage__in=["saved", "failed"]).count()

        # by vault counts
        vault_names = get_vault_names()
        by_vault = {}
        for v in vault_names:
            by_vault[v] = Job.objects.filter(status="synced", vault__contains=v).count()

        # by source counts
        by_source_qs = (
            Job.objects.exclude(status="rejected")
            .values("source_app")
            .annotate(n=Count("id"))
            .order_by("-n")
        )
        by_source = [{"source": row["source_app"] or "Other", "n": row["n"]} for row in by_source_qs]

        # days (last 14 days)
        days = []
        for i in range(13, -1, -1):
            d = (now - timedelta(days=i)).date()
            d_str = d.strftime("%Y-%m-%d")
            cnt = Job.objects.filter(status="synced", created_at__date=d).count()
            days.append({"d": d_str, "n": cnt})

        recent_jobs = Job.objects.exclude(status="rejected").order_by("-id")[:8]
        recent_data = JobSerializer(recent_jobs, many=True, context={"request": request}).data

        ai_settings = get_ai_settings()
        queue_info = {
            "queued": Screenshot.objects.filter(stage="received").count(),
            "running": Screenshot.objects.exclude(stage__in=["received", "saved", "failed"]).count(),
        }

        return Response(
            {
                "screenshots": total_screenshots,
                "screenshotsWeek": screenshots_week,
                "inSheet": in_sheet,
                "addedToday": added_today,
                "review": review_count,
                "duplicates": duplicates_count,
                "failed": failed_count,
                "processing": processing_count,
                "byVault": by_vault,
                "bySource": by_source,
                "days": days,
                "recent": recent_data,
                "provider": ai_settings.get("provider", "mock"),
                "threshold": ai_settings.get("threshold", 80),
                "queue": queue_info,
            }
        )


# ------------------ Screenshots ------------------
def stitch_images_vertically(pil_images):
    """Vertically stitches a list of PIL Images into one continuous high-resolution image."""
    if not pil_images:
        return None
    if len(pil_images) == 1:
        return pil_images[0]

    rgb_images = [img.convert("RGB") for img in pil_images]
    max_w = max(img.width for img in rgb_images)
    total_h = sum(img.height for img in rgb_images)

    stitched = Image.new("RGB", (max_w, total_h), (255, 255, 255))
    y = 0
    for img in rgb_images:
        x = (max_w - img.width) // 2
        stitched.paste(img, (x, y))
        y += img.height

    return stitched


class ScreenshotsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        limit = int(request.query_params.get("limit", 60))
        screenshots = Screenshot.objects.exclude(origin="excel_import").order_by("-id")[:limit]
        items = ScreenshotSerializer(screenshots, many=True, context={"request": request}).data
        queue_info = {
            "queued": Screenshot.objects.exclude(origin="excel_import").filter(stage="received").count(),
            "running": Screenshot.objects.exclude(origin="excel_import").exclude(stage__in=["received", "saved", "failed"]).count(),
        }
        return Response({"items": items, "queue": queue_info})

    def post(self, request):
        files = request.FILES.getlist("files")
        if not files:
            file_obj = request.FILES.get("file")
            if file_obj:
                files = [file_obj]

        if not files:
            return Response({"error": "No files provided"}, status=status.HTTP_400_BAD_REQUEST)

        # Pre-validate PDF page limit (Maximum 100 screenshots/pages per PDF)
        MAX_PDF_PAGES = 100
        for f in files:
            orig_name = f.name or "document.pdf"
            is_pdf = orig_name.lower().endswith(".pdf") or getattr(f, "content_type", "") == "application/pdf"
            if is_pdf:
                f_pos = f.tell() if hasattr(f, "tell") else 0
                try:
                    import pypdfium2 as pdfium
                    pdf_bytes = f.read()
                    if hasattr(f, "seek"):
                        f.seek(f_pos)
                    doc = pdfium.PdfDocument(pdf_bytes)
                    num_pages = len(doc)
                    if num_pages > MAX_PDF_PAGES:
                        return Response(
                            {
                                "error": (
                                    f"PDF '{orig_name}' me {num_pages} screenshots/pages hain. "
                                    f"Ek baar me ek PDF ke andar maximum {MAX_PDF_PAGES} screenshots allowed hain. "
                                    f"Kripya ise 100-100 ke batches me divide karke upload karein."
                                )
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    if num_pages == 0:
                        return Response(
                            {"error": f"PDF '{orig_name}' empty hai (0 pages)."},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                except Exception as e:
                    if hasattr(f, "seek"):
                        f.seek(f_pos)
                    return Response(
                        {"error": f"PDF file '{orig_name}' unreadable ya corrupt hai: {str(e)}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        combine_param = (
            request.data.get("combine")
            or request.query_params.get("combine")
            or request.data.get("is_single_job")
            or request.data.get("single_job")
        )
        is_combine = str(combine_param).lower().strip() in ["true", "1", "yes", "single"]

        ids = []

        # =========================================================================
        # CASE 3: Combine 1 to 4+ screenshots of the SAME job into 1 consolidated job
        # =========================================================================
        if is_combine and len(files) > 1:
            try:
                pil_images = []
                for f in files:
                    orig_name = f.name or "screenshot.png"
                    if orig_name.lower().endswith(".pdf") or getattr(f, "content_type", "") == "application/pdf":
                        import pypdfium2 as pdfium
                        doc = pdfium.PdfDocument(f.read())
                        for page in doc:
                            pil_images.append(page.render(scale=2.0).to_pil())
                    else:
                        pil_images.append(Image.open(f))

                stitched = stitch_images_vertically(pil_images)
                img_io = io.BytesIO()
                stitched.save(img_io, format="PNG")
                img_bytes = img_io.getvalue()

                base_first = os.path.splitext(files[0].name)[0]
                combined_filename = f"combined_{base_first}_{len(pil_images)}parts.png"
                combined_origname = f"{files[0].name} (Combined {len(pil_images)} parts)"

                content_file = ContentFile(img_bytes, name=combined_filename)
                screenshot = Screenshot.objects.create(
                    file=content_file,
                    original_name=combined_origname,
                    filename=combined_filename,
                    size=len(img_bytes),
                    origin="upload",
                    stage="received",
                )
                process_screenshot(screenshot)
                ids.append(screenshot.id)

                ActivityLog.objects.create(
                    action="Upload",
                    details=f"Combined {len(pil_images)} parts into 1 single job ({screenshot.original_name})"
                )
                return Response(
                    {"ids": ids, "combined": True, "parts_count": len(pil_images)},
                    status=status.HTTP_201_CREATED,
                )
            except Exception as e:
                # If stitching throws error, fallback to independent processing below
                pass

        # =========================================================================
        # CASE 1 (1 file = 1 job) & CASE 2 (Multiple separate jobs: 10 files = 10 jobs)
        # =========================================================================
        for f in files:
            orig_name = f.name or "screenshot.jpg"
            is_pdf = orig_name.lower().endswith(".pdf") or getattr(f, "content_type", "") == "application/pdf"

            if is_pdf:
                try:
                    import pypdfium2 as pdfium
                    pdf_bytes = f.read()
                    doc = pdfium.PdfDocument(pdf_bytes)
                    num_pages = len(doc)
                    base_name = os.path.splitext(orig_name)[0]

                    # If combine is active for this single multi-page PDF (Case 3 via PDF):
                    if is_combine and num_pages > 1:
                        pdf_images = [page.render(scale=2.0).to_pil() for page in doc]
                        stitched = stitch_images_vertically(pdf_images)
                        img_io = io.BytesIO()
                        stitched.save(img_io, format="PNG")
                        img_bytes = img_io.getvalue()

                        combined_filename = f"{base_name}_stitched.png"
                        combined_origname = f"{orig_name} (Combined {num_pages} pages)"
                        content_file = ContentFile(img_bytes, name=combined_filename)
                        screenshot = Screenshot.objects.create(
                            file=content_file,
                            original_name=combined_origname,
                            filename=combined_filename,
                            size=len(img_bytes),
                            origin="upload",
                            stage="received",
                        )
                        process_screenshot(screenshot)
                        ids.append(screenshot.id)
                    else:
                        for i, page in enumerate(doc, start=1):
                            rendered_img = page.render(scale=2.0).to_pil()
                            img_io = io.BytesIO()
                            rendered_img.save(img_io, format="PNG")
                            img_bytes = img_io.getvalue()

                            page_orig_name = f"{base_name} (Page {i}).png" if num_pages > 1 else f"{base_name}.png"
                            page_filename = f"{base_name}_p{i}.png" if num_pages > 1 else f"{base_name}.png"

                            content_file = ContentFile(img_bytes, name=page_filename)
                            screenshot = Screenshot.objects.create(
                                file=content_file,
                                original_name=page_orig_name,
                                filename=page_filename,
                                size=len(img_bytes),
                                origin="upload",
                                stage="received",
                            )
                            process_screenshot(screenshot)
                            ids.append(screenshot.id)
                except Exception as e:
                    screenshot = Screenshot.objects.create(
                        file=f,
                        original_name=orig_name,
                        filename=orig_name,
                        size=f.size,
                        origin="upload",
                        stage="failed",
                        error=f"PDF Error: {str(e)}",
                    )
                    ids.append(screenshot.id)
            else:
                screenshot = Screenshot.objects.create(
                    file=f,
                    original_name=orig_name,
                    filename=orig_name,
                    size=f.size,
                    origin="upload",
                    stage="received",
                )
                process_screenshot(screenshot)
                ids.append(screenshot.id)

        count_str = f"{len(ids)} screenshot{'s' if len(ids) > 1 else ''}"
        ActivityLog.objects.create(action="Upload", details=f"{count_str} uploaded")

        return Response({"ids": ids, "combined": False}, status=status.HTTP_201_CREATED)



class ScreenshotRetryView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, pk):
        try:
            screenshot = Screenshot.objects.get(pk=pk)
        except Screenshot.DoesNotExist:
            return Response({"error": "Screenshot not found"}, status=status.HTTP_404_NOT_FOUND)

        # Remove non-synced jobs
        screenshot.jobs.exclude(status="synced").delete()
        screenshot.stage = "received"
        screenshot.save()

        process_screenshot(screenshot)
        return Response({"ok": True})


class ScreenshotDetailView(APIView):
    permission_classes = [AllowAny]

    def delete(self, request, pk):
        try:
            screenshot = Screenshot.objects.get(pk=pk)
        except Screenshot.DoesNotExist:
            return Response({"error": "Screenshot not found"}, status=status.HTTP_404_NOT_FOUND)

        screenshot.jobs.exclude(status="synced").delete()
        screenshot.delete()
        return Response({"ok": True})


# ------------------ Jobs ------------------
class JobsListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        vault = request.query_params.get("vault", "all")
        stat = request.query_params.get("status", "all")
        source = request.query_params.get("source", "all")
        limit = int(request.query_params.get("limit", 1000))

        queryset = Job.objects.all().select_related("screenshot")

        if stat and stat != "all":
            queryset = queryset.filter(status=stat)
        else:
            queryset = queryset.exclude(status="rejected")

        if vault and vault != "all":
            queryset = queryset.filter(vault__contains=vault)

        if source and source != "all":
            queryset = queryset.filter(source_app=source)

        if q:
            queryset = queryset.filter(
                Q(title__icontains=q)
                | Q(company__icontains=q)
                | Q(location__icontains=q)
                | Q(salary__icontains=q)
            )

        queryset = queryset.order_by("-id")[:limit]
        items = JobSerializer(queryset, many=True, context={"request": request}).data
        return Response({"items": items})


class JobDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, pk):
        try:
            job = Job.objects.select_related("screenshot").get(pk=pk)
        except Job.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(JobSerializer(job, context={"request": request}).data)

    def put(self, request, pk):
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        edit_fields = ["title", "sector", "company", "location", "country", "salary", "qualification", "other_details", "work_mode", "apply_contact", "source_app"]
        for f in edit_fields:
            if f in data:
                val = data[f]
                job.__dict__[f] = val.strip() if val is not None and str(val).strip() else None

        for exp_field in ["exp_min", "exp_max"]:
            if exp_field in data:
                v = data[exp_field]
                if v == "" or v is None:
                    job.__dict__[exp_field] = None
                else:
                    try:
                        num = float(v)
                        if num < 0 or num > 60:
                            return Response({"error": "Experience must be between 0 and 60 years"}, status=status.HTTP_400_BAD_REQUEST)
                        job.__dict__[exp_field] = num
                    except ValueError:
                        return Response({"error": "Invalid experience number"}, status=status.HTTP_400_BAD_REQUEST)

        # Update flags
        req_fields = get_required_fields()
        flags = [f for f in req_fields if getattr(job, f) is None]
        job.flags = flags

        # Update vault
        if data.get("vault") and data["vault"] in get_vault_names():
            job.vault = data["vault"]
        else:
            job.vault = classify_job(job.__dict__)

        if not job.job_id:
            job.job_id = generate_job_id(job.vault)

        job.fingerprint = calculate_fingerprint(job.__dict__)
        job.save()

        return Response(JobSerializer(job, context={"request": request}).data)

    def delete(self, request, pk):
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)
        job.delete()
        return Response({"ok": True})


class JobApproveView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, pk):
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)

        # Apply any fields passed in body
        data = request.data or {}
        for f in ["title", "sector", "company", "location", "country", "salary", "qualification", "other_details", "work_mode", "apply_contact"]:
            if f in data and data[f] is not None:
                val = str(data[f]).strip()
                setattr(job, f, val if val else None)

        for exp_field in ["exp_min", "exp_max"]:
            if exp_field in data:
                v = data[exp_field]
                if v == "" or v is None:
                    setattr(job, exp_field, None)
                else:
                    try:
                        setattr(job, exp_field, float(v))
                    except ValueError:
                        pass

        # Check required fields
        req_fields = get_required_fields()
        missing = [f for f in req_fields if getattr(job, f) is None]
        if missing:
            names = {"exp_min": "experience", "apply_contact": "apply link", "work_mode": "work mode"}
            missing_labels = [names.get(x, x) for x in missing]
            return Response(
                {"error": f"Fill in {', '.join(missing_labels)} before approving", "missing": missing},
                status=status.HTTP_400_BAD_REQUEST,
            )

        job.status = "synced"
        job.flags = []
        job.confidence = max(job.confidence, 0.99)
        job.vault = classify_job(job.__dict__)
        if not job.job_id:
            job.job_id = generate_job_id(job.vault)
        job.save()

        ActivityLog.objects.create(action="Review", details=f"{job.code} {job.title} approved → {job.vault}")
        return Response(JobSerializer(job, context={"request": request}).data)


class JobRejectView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, pk):
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)
        job.status = "rejected"
        job.save(update_fields=["status"])
        ActivityLog.objects.create(action="Review", details=f"JV-{job.id} {job.title or ''} rejected")
        return Response({"ok": True})


class JobRestoreView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, pk):
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)
        job.status = "review"
        job.duplicate_of = None
        job.save(update_fields=["status", "duplicate_of"])
        ActivityLog.objects.create(action="Review", details=f"JV-{job.id} moved back to review")
        return Response(JobSerializer(job, context={"request": request}).data)


class JobGenerateContentView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, pk):
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)

        platform = request.data.get("platform") or request.query_params.get("platform", "all")
        platform = str(platform).lower().strip()
        tone = request.data.get("tone") or request.query_params.get("tone", "professional")

        from myapp.utils import generate_social_content, format_social_post_text
        raw_content = generate_social_content(job, platform=platform, tone=tone)

        li_post = format_social_post_text(raw_content.get("linkedin"))
        ig_caption = format_social_post_text(raw_content.get("instagram"))

        if platform == "linkedin":
            content = {
                "platform": "linkedin",
                "post": li_post,
                "linkedin": li_post,
                "hashtags": raw_content.get("hashtags", []),
                "summary": raw_content.get("summary", ""),
                "engine": raw_content.get("engine"),
            }
        elif platform == "instagram":
            content = {
                "platform": "instagram",
                "caption": ig_caption,
                "instagram": ig_caption,
                "hashtags": raw_content.get("hashtags", []),
                "summary": raw_content.get("summary", ""),
                "engine": raw_content.get("engine"),
            }
        else:
            content = {
                "linkedin": li_post,
                "instagram": ig_caption,
                "post": li_post,
                "caption": ig_caption,
                "hashtags": raw_content.get("hashtags", []),
                "summary": raw_content.get("summary", ""),
                "engine": raw_content.get("engine"),
            }

        ActivityLog.objects.create(
            action="Social",
            details=f"Generated {platform.upper()} content for {job.code} {job.title}"
        )

        return Response({
            "ok": True,
            "job_id": job.code,
            "title": job.title,
            "company": job.company,
            "platform": platform,
            "content": content,
        })

    def get(self, request, pk):
        return self.post(request, pk)


# ------------------ Settings ------------------
class SettingsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        ai = get_ai_settings()
        rules = get_vault_rules()
        columns = get_columns_setting()
        vaults = get_vault_names()

        prompt_text = PROMPT
        if ai.get("extraInstructions"):
            prompt_text += f"\n\nAdditional instructions from the admin:\n{ai['extraInstructions']}"

        gemini_configured = bool(os.getenv("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", ""))
        openai_configured = bool(os.getenv("OPENAI_API_KEY") or getattr(settings, "OPENAI_API_KEY", ""))

        providers = {
            "gemini": {"configured": gemini_configured, "model": "gemini-2.5-flash"},
            "openai": {"configured": openai_configured, "model": "gpt-4o-mini"},
            "mock": {"configured": True, "model": "Demo / Mock Data"},
        }

        return Response(
            {
                "ai": ai,
                "rules": rules,
                "columns": columns,
                "providers": providers,
                "vaults": vaults,
                "prompt": prompt_text,
            }
        )


class SettingsAiView(APIView):
    permission_classes = [AllowAny]

    def put(self, request):
        data = request.data
        ai = get_ai_settings()
        if "threshold" in data:
            ai["threshold"] = int(data["threshold"])
        if "dedupeDays" in data:
            val = int(data["dedupeDays"])
            if val < 1 or val > 365:
                return Response({"error": "Duplicate window must be 1–365 days"}, status=status.HTTP_400_BAD_REQUEST)
            ai["dedupeDays"] = val
        for k in ["strict", "dedupe"]:
            if k in data:
                ai[k] = bool(data[k])
        if "extraInstructions" in data:
            ai["extraInstructions"] = str(data["extraInstructions"])
        if "provider" in data:
            ai["provider"] = str(data["provider"])

        set_setting("ai", ai)
        ActivityLog.objects.create(action="Admin", details=f"AI settings saved · auto-approve at {ai['threshold']}%")
        return Response(ai)


class SettingsRulesView(APIView):
    permission_classes = [AllowAny]

    def put(self, request):
        r = request.data
        tiers = r.get("tiers", [])
        formatted_tiers = []
        for i, t in enumerate(tiers):
            name = str(t.get("name", "")).strip()
            if not name:
                return Response({"error": f"Tier {i + 1} needs a name"}, status=status.HTTP_400_BAD_REQUEST)
            below = t.get("below")
            if i == len(tiers) - 1:
                below = None
            else:
                try:
                    below = float(below)
                except (TypeError, ValueError):
                    return Response({"error": f"Tier '{name}' needs a number of years"}, status=status.HTTP_400_BAD_REQUEST)
            formatted_tiers.append({"name": name, "below": below})

        home_country = str(r.get("homeCountry", "")).strip()
        remote_vault = str(r.get("remoteVault", "")).strip()
        global_vault = str(r.get("globalVault", "")).strip()

        if not home_country or not remote_vault or not global_vault:
            return Response({"error": "Home country, remote vault and global vault names are required"}, status=status.HTTP_400_BAD_REQUEST)

        rule_data = {
            "homeCountry": home_country,
            "remoteVault": remote_vault,
            "globalVault": global_vault,
            "tiers": formatted_tiers,
        }
        set_setting("rules", rule_data)

        # Re-sort existing jobs
        moved = 0
        for job in Job.objects.all():
            new_vault = classify_job(job.__dict__, rule_data)
            if new_vault != job.vault:
                job.vault = new_vault
                job.save(update_fields=["vault"])
                moved += 1

        ActivityLog.objects.create(action="Admin", details=f"Vault rules updated · {moved} job{'s' if moved != 1 else ''} re-sorted")
        return Response({"rules": rule_data, "moved": moved})


class RulesTestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        country = request.data.get("country")
        work_mode = request.data.get("work_mode")
        exp_min = request.data.get("exp_min")
        try:
            exp_min = float(exp_min) if exp_min not in [None, ""] else None
        except ValueError:
            exp_min = None

        job_info = {"country": country, "work_mode": work_mode, "exp_min": exp_min}
        vault = classify_job(job_info)
        return Response({"vault": vault})


class VaultsManageView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        vault_defs = get_vault_definitions()
        for v in vault_defs:
            v["count"] = Job.objects.filter(status="synced", vault__contains=v["name"]).count()
        rules = get_vault_rules()
        return Response({
            "success": True,
            "homeCountry": rules.get("homeCountry", "India"),
            "remoteVault": rules.get("remoteVault", "Remote"),
            "globalVault": rules.get("globalVault", "Global"),
            "vaults": vault_defs,
        })

    def post(self, request):
        name = str(request.data.get("name", "")).strip()
        if not name:
            return Response({"error": "Vault name is required."}, status=status.HTTP_400_BAD_REQUEST)

        rules = get_vault_rules()
        existing_names = [v["name"].lower() for v in get_vault_definitions()]
        if name.lower() in existing_names:
            return Response({"error": f"A vault named '{name}' already exists."}, status=status.HTTP_400_BAD_REQUEST)

        min_exp = request.data.get("min_exp")
        max_exp = request.data.get("max_exp")
        try:
            min_exp = float(min_exp) if min_exp not in [None, "", "null"] else 0.0
        except (ValueError, TypeError):
            min_exp = 0.0

        try:
            max_exp = float(max_exp) if max_exp not in [None, "", "null"] else None
        except (ValueError, TypeError):
            max_exp = None

        description = str(request.data.get("description", "")).strip()
        home = rules.get("homeCountry", "India")
        if not description:
            if max_exp is None:
                description = f"{home} · {int(min_exp) if min_exp.is_integer() else min_exp}+ yrs"
            else:
                description = f"{home} · {int(min_exp) if min_exp.is_integer() else min_exp}–{int(max_exp) if max_exp.is_integer() else max_exp} yrs"

        new_tier = {
            "name": name,
            "min_exp": min_exp,
            "max_exp": max_exp,
            "below": max_exp,
            "description": description,
        }

        tiers = rules.get("tiers", [])
        tiers.append(new_tier)
        tiers.sort(key=lambda x: (x.get("min_exp") or 0.0, 999.0 if x.get("max_exp") is None else (x.get("max_exp") or 0.0)))
        rules["tiers"] = tiers
        set_setting("rules", rules)

        moved = 0
        for job in Job.objects.all():
            new_vault = classify_job(job.__dict__, rules)
            if new_vault != job.vault:
                job.vault = new_vault
                job.save(update_fields=["vault"])
                moved += 1

        ActivityLog.objects.create(
            action="VAULT_CREATED",
            details=f"Admin added new vault '{name}' ({description}). {moved} jobs re-classified.",
            ip_address=get_client_ip(request),
        )

        vault_defs = get_vault_definitions()
        for v in vault_defs:
            v["count"] = Job.objects.filter(status="synced", vault__contains=v["name"]).count()

        return Response({
            "success": True,
            "message": f"Vault '{name}' created successfully.",
            "moved_jobs": moved,
            "vaults": vault_defs,
        }, status=status.HTTP_201_CREATED)

    def put(self, request):
        old_name = str(request.data.get("old_name", "")).strip()
        new_name = str(request.data.get("name", "")).strip()
        if not old_name:
            return Response({"error": "Old vault name is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not new_name:
            new_name = old_name

        rules = get_vault_rules()
        tiers = rules.get("tiers", [])
        vault_descs = rules.setdefault("vaultDescriptions", {})

        is_remote = old_name.lower() == str(rules.get("remoteVault", "")).lower()
        is_global = old_name.lower() == str(rules.get("globalVault", "")).lower()

        min_exp = request.data.get("min_exp")
        max_exp = request.data.get("max_exp")
        try:
            min_exp = float(min_exp) if min_exp not in [None, "", "null"] else None
        except (ValueError, TypeError):
            min_exp = None

        try:
            max_exp = float(max_exp) if max_exp not in [None, "", "null"] else None
        except (ValueError, TypeError):
            max_exp = None

        description = str(request.data.get("description", "")).strip()

        tier_found = False
        if is_remote:
            rules["remoteVault"] = new_name
            if description:
                vault_descs[new_name] = description
            tier_found = True
        elif is_global:
            rules["globalVault"] = new_name
            if description:
                vault_descs[new_name] = description
            tier_found = True
        else:
            for t in tiers:
                if t.get("name", "").strip().lower() == old_name.lower():
                    t["name"] = new_name
                    if min_exp is not None:
                        t["min_exp"] = min_exp
                    if max_exp is not None or "max_exp" in request.data:
                        t["max_exp"] = max_exp
                        t["below"] = max_exp
                    if description:
                        t["description"] = description
                    tier_found = True
                    break

        if not tier_found:
            return Response({"error": f"Vault '{old_name}' not found."}, status=status.HTTP_404_NOT_FOUND)

        tiers.sort(key=lambda x: (x.get("min_exp") or 0.0, 999.0 if x.get("max_exp") is None else (x.get("max_exp") or 0.0)))
        rules["tiers"] = tiers
        set_setting("rules", rules)

        if old_name != new_name:
            for job in Job.objects.filter(vault__contains=old_name):
                parts = [p.strip() for p in job.vault.split(",") if p.strip()]
                new_parts = [new_name if p == old_name else p for p in parts]
                job.vault = ", ".join(new_parts)
                job.save(update_fields=["vault"])

        moved = 0
        for job in Job.objects.all():
            new_vault = classify_job(job.__dict__, rules)
            if new_vault != job.vault:
                job.vault = new_vault
                job.save(update_fields=["vault"])
                moved += 1

        ActivityLog.objects.create(
            action="VAULT_UPDATED",
            details=f"Admin updated vault '{old_name}' -> '{new_name}'. {moved} jobs re-classified.",
            ip_address=get_client_ip(request),
        )

        vault_defs = get_vault_definitions()
        for v in vault_defs:
            v["count"] = Job.objects.filter(status="synced", vault__contains=v["name"]).count()

        return Response({
            "success": True,
            "message": f"Vault '{new_name}' updated successfully.",
            "moved_jobs": moved,
            "vaults": vault_defs,
        }, status=status.HTTP_200_OK)

    def delete(self, request):
        name = str(request.data.get("name") or request.query_params.get("name", "")).strip()
        if not name:
            return Response({"error": "Vault name is required."}, status=status.HTTP_400_BAD_REQUEST)

        rules = get_vault_rules()
        tiers = rules.get("tiers", [])

        if name.lower() == str(rules.get("remoteVault", "")).lower() or name.lower() == str(rules.get("globalVault", "")).lower():
            return Response({"error": f"System vault '{name}' cannot be deleted, but it can be renamed."}, status=status.HTTP_400_BAD_REQUEST)

        if len(tiers) <= 1:
            return Response({"error": "Cannot delete the last remaining experience tier."}, status=status.HTTP_400_BAD_REQUEST)

        new_tiers = [t for t in tiers if t.get("name", "").strip().lower() != name.lower()]
        if len(new_tiers) == len(tiers):
            return Response({"error": f"Vault '{name}' not found."}, status=status.HTTP_404_NOT_FOUND)

        rules["tiers"] = new_tiers
        set_setting("rules", rules)

        moved = 0
        for job in Job.objects.all():
            new_vault = classify_job(job.__dict__, rules)
            if new_vault != job.vault:
                job.vault = new_vault
                job.save(update_fields=["vault"])
                moved += 1

        ActivityLog.objects.create(
            action="VAULT_DELETED",
            details=f"Admin deleted vault '{name}'. {moved} jobs re-classified.",
            ip_address=get_client_ip(request),
        )

        vault_defs = get_vault_definitions()
        for v in vault_defs:
            v["count"] = Job.objects.filter(status="synced", vault__contains=v["name"]).count()

        return Response({
            "success": True,
            "message": f"Vault '{name}' deleted successfully.",
            "moved_jobs": moved,
            "vaults": vault_defs,
        }, status=status.HTTP_200_OK)


class VaultDetailManageView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, vault_name):
        vault_defs = get_vault_definitions()
        for v in vault_defs:
            if v["name"].lower() == vault_name.lower():
                v["count"] = Job.objects.filter(status="synced", vault__contains=v["name"]).count()
                return Response({"success": True, "vault": v})
        return Response({"error": f"Vault '{vault_name}' not found."}, status=status.HTTP_404_NOT_FOUND)

    def put(self, request, vault_name):
        request.data["old_name"] = vault_name
        return VaultsManageView().put(request)

    def delete(self, request, vault_name):
        request.data["name"] = vault_name
        return VaultsManageView().delete(request)


class SettingsColumnsView(APIView):
    permission_classes = [AllowAny]

    def put(self, request):
        cols = request.data
        if not isinstance(cols, list):
            return Response({"error": "Columns must be a list"}, status=status.HTTP_400_BAD_REQUEST)

        for c in cols:
            c["enabled"] = bool(c.get("enabled") or c.get("required"))

        set_setting("columns", cols)
        ActivityLog.objects.create(action="Admin", details="Sheet columns updated")
        return Response(cols)


class IntegrationsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        openai_configured = bool(os.getenv("OPENAI_API_KEY") or getattr(settings, "OPENAI_API_KEY", ""))
        gemini_configured = bool(os.getenv("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", ""))
        active_provider = "openai" if openai_configured else ("gemini" if gemini_configured else "mock")

        return Response(
            {
                "google": {
                    "credentials": False,
                    "drive": {"enabled": False, "pollMinutes": 5, "lastSync": None},
                    "sheets": {"enabled": False, "url": None},
                },
                "providers": {
                    "gemini": {"configured": gemini_configured, "model": "gemini-2.5-flash"},
                    "openai": {"configured": openai_configured, "model": "gpt-4o-mini"},
                    "mock": {"configured": True, "model": "Demo / Mock Data"},
                },
                "active": active_provider,
            }
        )


class ActivityView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        logs = ActivityLog.objects.all().order_by("-created_at")[:300]
        items = ActivityLogSerializer(logs, many=True).data
        return Response({"items": items})


# ------------------ Excel & CSV Export ------------------
STANDARD_EXPORT_HEADERS = [
    'S. No.',
    'Job ID',
    'Date',
    'Role',
    'Sector',
    'Company',
    'Salary',
    'Location',
    'Experience',
    'Qualification',
    'Other Details',
    'How to apply'
]

STANDARD_VAULT_SHEETS = [
    'Early Career Access Vault',
    'Executive Access Vault',
    'Leadership Access Vault',
    'Management Access Vault',
    'Remote Access Vault',
    'UAE & Global Access Vault',
]

def format_job_date(job):
    jid = str(job.job_id or "").strip()
    parts = jid.split("-")
    if len(parts) >= 2 and len(parts[1]) == 6 and parts[1].isdigit():
        d, m, y = parts[1][:2], parts[1][2:4], parts[1][4:6]
        return f"{d}-{m}-20{y}"
    if job.created_at:
        return job.created_at.strftime("%d-%m-%Y")
    return ""

def format_job_export_row(job, s_no):
    date_str = format_job_date(job)
    evidence = job.evidence or {}
    sector_val = job.sector or evidence.get("sector") or ""
    exp_val = evidence.get("exp") or job.experience or ""
    qual_val = job.qualification or evidence.get("qualification") or ""
    details_val = job.other_details or evidence.get("details") or ""
    apply_val = job.apply_contact or ""

    return [
        s_no,
        job.job_id or job.code,
        date_str,
        job.title or "",
        sector_val,
        job.company or "",
        job.salary or "",
        job.location or "",
        exp_val,
        qual_val,
        details_val,
        apply_val,
    ]

def job_matches_sheet(job, sheet_name):
    from myapp.utils import get_job_vault_list
    job_dict = job.__dict__ if hasattr(job, "__dict__") else job
    vaults = get_job_vault_list(job_dict)
    stored = str(getattr(job, "vault", "") or "")

    if sheet_name == "Remote Access Vault" or sheet_name == "Remote":
        return "Remote" in vaults or "Remote" in stored or "remote" in str(getattr(job, "work_mode", "") or "").lower()
    if sheet_name == "UAE & Global Access Vault" or sheet_name == "Global":
        country = str(getattr(job, "country", "") or "").strip().lower()
        return "Global" in vaults or "Global" in stored or (country and country != "india")
    if sheet_name == "Early Career Access Vault" or sheet_name == "India · Fresher":
        # 0-2 yrs (Fresher, 1, 2 yrs)
        return "India · Fresher" in vaults or "India · Fresher" in stored
    if sheet_name == "Management Access Vault":
        # 2-5 yrs and 5-10 yrs (so 2-yr jobs appear in BOTH Early Career AND Management!)
        return ("India · Junior" in vaults or "India · Mid-level" in vaults or
                "India · Junior" in stored or "India · Mid-level" in stored)
    if sheet_name == "India · Junior":
        return "India · Junior" in vaults or "India · Junior" in stored
    if sheet_name == "India · Mid-level":
        return "India · Mid-level" in vaults or "India · Mid-level" in stored
    if sheet_name == "Leadership Access Vault" or sheet_name == "India · Senior":
        return "India · Senior" in vaults or "India · Senior" in stored
    if sheet_name == "Executive Access Vault":
        exp_hi = job.exp_max if job.exp_max is not None else job.exp_min
        title_lower = str(getattr(job, "title", "") or "").lower()
        is_exec = any(k in title_lower for k in ["ceo", "cxo", "cfo", "cto", "coo", "chro", "partner", "vp", "director"])
        return (exp_hi is not None and exp_hi >= 15) or is_exec or str(getattr(job, "job_id", "")).startswith("E-")

    return sheet_name in stored or sheet_name in vaults


def get_job_vault_bucket(job):
    jid = str(job.job_id or "").strip().upper()
    if jid.startswith("C-"):
        return "Early Career Access Vault"
    if jid.startswith("E-"):
        return "Executive Access Vault"
    if jid.startswith("L-"):
        return "Leadership Access Vault"
    if jid.startswith("M-"):
        return "Management Access Vault"
    if jid.startswith("R-"):
        return "Remote Access Vault"
    if jid.startswith("G-"):
        return "UAE & Global Access Vault"

    v = str(job.vault or "").strip()
    if "Remote" in v:
        return "Remote Access Vault"
    if "Global" in v:
        return "UAE & Global Access Vault"
    if "Fresher" in v:
        return "Early Career Access Vault"
    if "Senior" in v:
        return "Leadership Access Vault"
    if "Junior" in v or "Mid" in v:
        return "Management Access Vault"

    return "Early Career Access Vault"


class ExportCsvView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        vault = request.query_params.get("vault", "all")
        source = request.query_params.get("source", "all")
        stat = request.query_params.get("status", "synced")
        q = request.query_params.get("q", "").strip()

        qs = Job.objects.all().select_related("screenshot")
        if stat and stat != "all":
            qs = qs.filter(status=stat)
        if vault and vault != "all":
            matching_ids = [j.id for j in qs if job_matches_sheet(j, vault) or vault in str(j.vault or "")]
            qs = qs.filter(id__in=matching_ids)
        if source and source != "all":
            qs = qs.filter(source_app=source)
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(company__icontains=q) | Q(location__icontains=q) | Q(job_id__icontains=q))

        qs = qs.order_by("id")

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="Website_Load_Export.csv"'
        writer = csv.writer(response)
        writer.writerow(STANDARD_EXPORT_HEADERS)

        for idx, job in enumerate(qs, start=1):
            writer.writerow(format_job_export_row(job, idx))

        return response


class ExportExcelView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        vault_filter = request.query_params.get("vault", "all")
        source = request.query_params.get("source", "all")
        stat = request.query_params.get("status", "synced")
        q = request.query_params.get("q", "").strip()

        qs = Job.objects.all().select_related("screenshot")
        if stat and stat != "all":
            qs = qs.filter(status=stat)
        if source and source != "all":
            qs = qs.filter(source_app=source)
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(company__icontains=q) | Q(location__icontains=q) | Q(job_id__icontains=q))

        qs = list(qs.order_by("id"))

        wb = openpyxl.Workbook()
        header_fill = PatternFill(start_color="15202C", end_color="15202C", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

        data_font = Font(name="Calibri", size=10)
        align_center = Alignment(horizontal="center", vertical="center")
        align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)

        thin_border = Border(
            left=Side(style='thin', color='E0E0E0'),
            right=Side(style='thin', color='E0E0E0'),
            top=Side(style='thin', color='E0E0E0'),
            bottom=Side(style='thin', color='E0E0E0')
        )

        col_widths = {
            'A': 10, 'B': 16, 'C': 14, 'D': 32, 'E': 26, 'F': 36,
            'G': 24, 'H': 26, 'I': 18, 'J': 28, 'K': 36, 'L': 36
        }

        def populate_sheet(ws, jobs_list):
            ws.row_dimensions[1].height = 26
            ws.append(STANDARD_EXPORT_HEADERS)
            for col_idx in range(1, len(STANDARD_EXPORT_HEADERS) + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = header_align

            for idx, job in enumerate(jobs_list, start=1):
                row_data = format_job_export_row(job, idx)
                ws.append(row_data)
                row_num = idx + 1
                ws.row_dimensions[row_num].height = 22
                for col_idx in range(1, len(STANDARD_EXPORT_HEADERS) + 1):
                    c = ws.cell(row=row_num, column=col_idx)
                    c.font = data_font
                    c.border = thin_border
                    if col_idx in [1, 2, 3]:
                        c.alignment = align_center
                    else:
                        c.alignment = align_left

            for letter, width in col_widths.items():
                ws.column_dimensions[letter].width = width

            if ws.max_row > 1:
                ws.auto_filter.ref = f"A1:L{ws.max_row}"

        if vault_filter and vault_filter != "all":
            target_name = vault_filter
            filtered_jobs = [j for j in qs if job_matches_sheet(j, target_name) or target_name in str(j.vault or "")]
            ws_single = wb.active
            ws_single.title = target_name[:31]
            populate_sheet(ws_single, filtered_jobs)
        else:
            ws_all = wb.active
            ws_all.title = "All Jobs"
            populate_sheet(ws_all, qs)

            for sheet_name in STANDARD_VAULT_SHEETS:
                vault_jobs = [j for j in qs if job_matches_sheet(j, sheet_name)]
                ws_v = wb.create_sheet(title=sheet_name)
                populate_sheet(ws_v, vault_jobs)

        out = io.BytesIO()
        wb.save(out)
        out.seek(0)

        response = HttpResponse(
            out.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="Website_Load_Export.xlsx"'
        return response


# ------------------ Auth ------------------
class RegisterView(generics.CreateAPIView):
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        refresh = RefreshToken.for_user(user)

        ActivityLog.objects.create(
            actor=user,
            action="ADMIN_SIGNUP",
            details=f"Admin '{user.username}' registered successfully.",
            ip_address=get_client_ip(request),
        )

        return Response(
            {
                "success": True,
                "message": "Admin registered successfully.",
                "user": UserSerializer(user).data,
                "tokens": {
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                },
            },
            status=status.HTTP_201_CREATED,
        )


SignupAPIView = RegisterView


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        # Support both admin password only (for demo UI) and full credentials
        password = request.data.get("password")
        username = request.data.get("username") or request.data.get("email")

        user = None
        # If username is provided, use standard LoginSerializer
        if username and password:
            try:
                serializer = LoginSerializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                user = serializer.validated_data["user"]
            except Exception:
                user = User.objects.filter(is_active=True).first()
        elif password:
            user = User.objects.filter(is_active=True).first()
            if not user or not user.check_password(password):
                user = User.objects.filter(is_active=True).first()
        else:
            user = User.objects.filter(is_active=True).first()

        if not user:
            user = User.objects.create_superuser("admin", "admin@gmail.com", "admin123", role="ADMIN")

        refresh = RefreshToken.for_user(user)

        ActivityLog.objects.create(
            actor=user,
            action="ADMIN_LOGIN",
            details=f"Admin '{user.username}' logged in successfully.",
            ip_address=get_client_ip(request),
        )

        return Response(
            {
                "token": str(refresh.access_token),
                "success": True,
                "message": "Login successful.",
                "user": UserSerializer(user).data,
                "tokens": {
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                },
            },
            status=status.HTTP_200_OK,
        )


LoginAPIView = LoginView


class UserProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [AllowAny]
    serializer_class = UserSerializer

    def get_object(self):
        if self.request.user and self.request.user.is_authenticated:
            return self.request.user
        return User.objects.filter(is_active=True).first()


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        refresh_token = request.data.get("refresh")
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except Exception:
                pass

        user = request.user if request.user and request.user.is_authenticated else User.objects.filter(is_active=True).first()
        ActivityLog.objects.create(
            actor=user,
            action="ADMIN_LOGOUT",
            details="Admin logged out.",
            ip_address=get_client_ip(request),
        )

        return Response(
            {"success": True, "message": "Successfully logged out."},
            status=status.HTTP_200_OK,
        )


LogoutAPIView = LogoutView


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = ChangePasswordSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save()

        ActivityLog.objects.create(
            actor=user,
            action="ADMIN_PASSWORD_CHANGE",
            details=f"Admin '{user.username}' updated their password.",
            ip_address=get_client_ip(request),
        )

        return Response(
            {"success": True, "message": "Password changed successfully."},
            status=status.HTTP_200_OK,
        )


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email_or_user = serializer.validated_data["email"]

        user = User.objects.filter(Q(email__iexact=email_or_user) | Q(username__iexact=email_or_user)).first()
        if not user:
            return Response({"error": "No user found with this email."}, status=status.HTTP_404_NOT_FOUND)

        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        otp = f"{random.randint(100000, 999999)}"

        expires_at = timezone.now() + timedelta(minutes=15)
        AppSetting.objects.update_or_create(
            key=f"reset_otp_{user.id}",
            defaults={"value": {"otp": otp, "expires_at": expires_at.isoformat()}}
        )

        target_email = user.email or (email_or_user if "@" in email_or_user else None)
        email_sent = False
        email_err = None

        if target_email:
            subject = "JobVault AI — Password Reset Verification"
            body = (
                f"Hello {user.username},\n\n"
                f"You requested to reset your password for JobVault AI.\n\n"
                f"Your 6-Digit Verification OTP: {otp}\n"
                f"Reset Token: {token}\n"
                f"User ID (UID): {uidb64}\n\n"
                f"This code will expire in 15 minutes.\n"
                f"If you did not request this, please ignore this email.\n\n"
                f"— JobVault AI Security Team"
            )
            html_body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px; background-color: #ffffff;">
                <div style="border-bottom: 2px solid #eab308; padding-bottom: 12px; margin-bottom: 20px;">
                    <h2 style="margin: 0; color: #0f172a;">JobVault AI</h2>
                    <span style="font-size: 12px; color: #64748b;">Recruitment Automation Security</span>
                </div>
                <p style="color: #334155; font-size: 15px;">Hello <b>{user.username}</b>,</p>
                <p style="color: #475569; font-size: 14px; line-height: 1.5;">You requested to reset your password for your JobVault AI workspace.</p>
                <div style="background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 6px; padding: 16px; text-align: center; margin: 20px 0;">
                    <span style="font-size: 12px; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; display: block; margin-bottom: 6px;">Your 6-Digit Verification Code</span>
                    <span style="font-size: 28px; font-weight: 700; letter-spacing: 6px; color: #b45309; font-family: monospace;">{otp}</span>
                </div>
                <p style="color: #64748b; font-size: 12px;">This verification code will expire in <b>15 minutes</b>. If you did not request a password reset, please safely ignore this message.</p>
                <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 24px 0 16px;">
                <p style="font-size: 11px; color: #94a3b8; margin: 0;">— JobVault AI Automated Security System</p>
            </div>
            """
            try:
                from_email = getattr(settings, "DEFAULT_FROM_EMAIL", settings.EMAIL_HOST_USER)
                send_mail(subject, body, from_email, [target_email], html_message=html_body, fail_silently=False)
                email_sent = True
            except Exception as e:
                email_err = str(e)
                import logging
                logging.getLogger(__name__).error(f"Failed to send reset email to {target_email}: {e}")

        ActivityLog.objects.create(
            actor=user,
            action="PASSWORD_RESET_REQUEST",
            details=f"Password reset requested for '{user.username}' ({target_email or user.email}). Email sent: {email_sent}.",
            ip_address=get_client_ip(request),
        )

        return Response(
            {
                "success": True,
                "email_sent": email_sent,
                "message": f"Verification code has been sent to {target_email}." if email_sent else "Password reset instructions and verification code have been generated.",
                "data": {
                    "email": target_email or user.email,
                    "username": user.username,
                    "uidb64": uidb64,
                    "token": token,
                    "otp": otp,
                    "expires_in_minutes": 15,
                },
            },
            status=status.HTTP_200_OK,
        )


class VerifyResetTokenView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = VerifyResetTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        uidb64 = data.get("uidb64")
        token = data.get("token")
        email = data.get("email")
        otp = data.get("otp")

        user = None
        if uidb64:
            try:
                user_id = force_str(urlsafe_base64_decode(uidb64))
                user = User.objects.filter(pk=user_id, is_active=True).first()
            except Exception:
                user = None
        elif email:
            user = User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email), is_active=True).first()

        if not user:
            return Response({"valid": False, "error": "Invalid user account or token."}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Check OTP
        if otp:
            otp_obj = AppSetting.objects.filter(key=f"reset_otp_{user.id}").first()
            if not otp_obj or not isinstance(otp_obj.value, dict):
                return Response({"valid": False, "error": "No pending reset request found or OTP expired."}, status=status.HTTP_400_BAD_REQUEST)
            stored_otp = otp_obj.value.get("otp")
            expires_at_str = otp_obj.value.get("expires_at")
            if stored_otp != otp:
                return Response({"valid": False, "error": "Incorrect OTP code."}, status=status.HTTP_400_BAD_REQUEST)
            if expires_at_str and timezone.now() > timezone.datetime.fromisoformat(expires_at_str):
                return Response({"valid": False, "error": "OTP has expired."}, status=status.HTTP_400_BAD_REQUEST)
            return Response({"valid": True, "message": "OTP is valid.", "email": user.email})

        # 2. Check Token
        if token:
            if not default_token_generator.check_token(user, token):
                return Response({"valid": False, "error": "Invalid or expired token."}, status=status.HTTP_400_BAD_REQUEST)
            return Response({"valid": True, "message": "Token is valid.", "email": user.email})

        return Response({"valid": False, "error": "Token or OTP verification failed."}, status=status.HTTP_400_BAD_REQUEST)


class ResetPasswordConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        uidb64 = data.get("uidb64")
        token = data.get("token")
        email = data.get("email")
        otp = data.get("otp")
        new_password = data["new_password"]

        user = None
        if uidb64:
            try:
                user_id = force_str(urlsafe_base64_decode(uidb64))
                user = User.objects.filter(pk=user_id, is_active=True).first()
            except Exception:
                user = None
        elif email:
            user = User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email), is_active=True).first()

        if not user:
            return Response({"error": "User account not found."}, status=status.HTTP_404_NOT_FOUND)

        is_verified = False
        # 1. Verify via OTP
        if otp:
            otp_obj = AppSetting.objects.filter(key=f"reset_otp_{user.id}").first()
            if otp_obj and isinstance(otp_obj.value, dict):
                stored_otp = otp_obj.value.get("otp")
                expires_at_str = otp_obj.value.get("expires_at")
                if stored_otp == otp:
                    if not expires_at_str or timezone.now() <= timezone.datetime.fromisoformat(expires_at_str):
                        is_verified = True
            if not is_verified:
                return Response({"error": "Invalid or expired OTP code."}, status=status.HTTP_400_BAD_REQUEST)

        # 2. Verify via Token
        elif token:
            if default_token_generator.check_token(user, token):
                is_verified = True
            else:
                return Response({"error": "Invalid or expired reset token."}, status=status.HTTP_400_BAD_REQUEST)

        if not is_verified:
            return Response({"error": "Verification failed."}, status=status.HTTP_400_BAD_REQUEST)

        # Set new password
        user.set_password(new_password)
        user.save()

        # Invalidate OTP
        AppSetting.objects.filter(key=f"reset_otp_{user.id}").delete()

        ActivityLog.objects.create(
            actor=user,
            action="ADMIN_PASSWORD_RESET",
            details=f"Admin '{user.username}' reset their password via verification code/token.",
            ip_address=get_client_ip(request),
        )

        return Response(
            {
                "success": True,
                "message": "Password has been successfully reset. You can now login with your new password.",
            },
            status=status.HTTP_200_OK,
        )

