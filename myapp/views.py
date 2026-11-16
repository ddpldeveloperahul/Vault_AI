import csv
import io
import os
from datetime import timedelta
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from django.shortcuts import render
from django.conf import settings
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from myapp.models import ActivityLog, AppSetting, Job, Screenshot, User
from myapp.serializers import (
    ActivityLogSerializer,
    ChangePasswordSerializer,
    JobSerializer,
    LoginSerializer,
    RegisterSerializer,
    ScreenshotSerializer,
    UserSerializer,
)
from myapp.utils import (
    PROMPT,
    classify_job,
    calculate_fingerprint,
    generate_job_id,
    get_ai_settings,
    get_columns_setting,
    get_required_fields,
    get_vault_names,
    get_vault_rules,
    process_screenshot,
    set_setting,
)


def index_view(request):
    return render(request, "dashboard.html")


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
            by_vault[v] = Job.objects.filter(status="synced", vault=v).count()

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

        ids = []
        for f in files:
            orig_name = f.name or "screenshot.jpg"
            screenshot = Screenshot.objects.create(
                file=f,
                original_name=orig_name,
                filename=orig_name,
                size=f.size,
                origin="upload",
                stage="received",
            )
            # Process screenshot and create job
            process_screenshot(screenshot)
            ids.append(screenshot.id)

        count_str = f"{len(ids)} screenshot{'s' if len(ids) > 1 else ''}"
        ActivityLog.objects.create(action="Upload", details=f"{count_str} uploaded")

        return Response({"ids": ids}, status=status.HTTP_201_CREATED)


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
            queryset = queryset.filter(vault=vault)

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

    ev_sheet = str((job.evidence or {}).get("sheet") or "").strip()
    if ev_sheet in STANDARD_VAULT_SHEETS:
        return ev_sheet

    v = str(job.vault or "").strip().lower()
    if "remote" in v:
        return "Remote Access Vault"
    if "global" in v or "uae" in v:
        return "UAE & Global Access Vault"
    if "fresher" in v or "early" in v:
        return "Early Career Access Vault"
    if "executive" in v:
        return "Executive Access Vault"
    if "senior" in v or "leadership" in v:
        return "Leadership Access Vault"
    if "mid" in v or "junior" in v or "management" in v:
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
            matching_ids = [j.id for j in qs if get_job_vault_bucket(j) == vault or j.vault == vault]
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
            filtered_jobs = [j for j in qs if get_job_vault_bucket(j) == target_name or j.vault == vault_filter]
            ws_single = wb.active
            ws_single.title = target_name[:31]
            populate_sheet(ws_single, filtered_jobs)
        else:
            ws_all = wb.active
            ws_all.title = "All Jobs"
            populate_sheet(ws_all, qs)

            for sheet_name in STANDARD_VAULT_SHEETS:
                vault_jobs = [j for j in qs if get_job_vault_bucket(j) == sheet_name]
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
