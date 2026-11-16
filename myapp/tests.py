import io
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from myapp.models import ActivityLog, Job, Screenshot, User
from myapp.utils import get_vault_rules


class JobVaultAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="adminuser",
            email="admin@jobvault.ai",
            password="SecurePassword123!",
            role="ADMIN",
        )

    def test_health_api(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data.get("ok"))

    def test_stats_api(self):
        res = self.client.get("/api/stats")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("screenshots", res.data)
        self.assertIn("inSheet", res.data)
        self.assertIn("byVault", res.data)

    def test_screenshot_upload_and_auto_extraction(self):
        # Create dummy image file
        dummy_file = SimpleUploadedFile(
            "IMG-20261106-WA0191.jpg",
            b"fake-image-bytes",
            content_type="image/jpeg"
        )
        res = self.client.post("/api/screenshots", {"files": [dummy_file]}, format="multipart")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn("ids", res.data)
        self.assertEqual(len(res.data["ids"]), 1)

        # Check screenshot created
        shot_id = res.data["ids"][0]
        shot = Screenshot.objects.get(id=shot_id)
        self.assertEqual(shot.stage, "saved")
        self.assertTrue(shot.jobs.exists())

        job = shot.jobs.first()
        self.assertTrue(job.title)
        self.assertIn(job.status, ["synced", "review", "duplicate"])

    def test_jobs_list_and_filter(self):
        shot = Screenshot.objects.create(filename="test.jpg", original_name="test.jpg")
        job = Job.objects.create(
            screenshot=shot,
            title="Python Developer",
            company="Tech Corp",
            location="Dehradun",
            status="synced",
            vault="India · Fresher"
        )

        # List all
        res = self.client.get("/api/jobs")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(any(j["title"] == "Python Developer" for j in res.data["items"]))

        # Filter by search
        res_search = self.client.get("/api/jobs?q=Python")
        self.assertEqual(len(res_search.data["items"]), 1)

        # Filter by vault
        res_vault = self.client.get("/api/jobs?vault=India · Fresher")
        self.assertEqual(len(res_vault.data["items"]), 1)

    def test_job_approve_reject_restore(self):
        shot = Screenshot.objects.create(filename="shot.jpg", original_name="shot.jpg")
        job = Job.objects.create(
            screenshot=shot,
            title="Data Analyst",
            company="Northwind",
            location="Bengaluru",
            exp_min=2.0,
            status="review",
            flags=[]
        )

        # Approve
        res = self.client.post(f"/api/jobs/{job.id}/approve")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        job.refresh_from_db()
        self.assertEqual(job.status, "synced")

        # Reject
        res = self.client.post(f"/api/jobs/{job.id}/reject")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        job.refresh_from_db()
        self.assertEqual(job.status, "rejected")

        # Restore
        res = self.client.post(f"/api/jobs/{job.id}/restore")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        job.refresh_from_db()
        self.assertEqual(job.status, "review")

    def test_settings_and_rule_test(self):
        # GET settings
        res = self.client.get("/api/settings")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("ai", res.data)
        self.assertIn("rules", res.data)
        self.assertIn("vaults", res.data)

        # Test Rule
        res_rule = self.client.post("/api/rules/test", {
            "country": "India",
            "work_mode": "Onsite",
            "exp_min": 1
        }, format="json")
        self.assertEqual(res_rule.status_code, status.HTTP_200_OK)
        self.assertEqual(res_rule.data["vault"], "India · Fresher")

        # Test Remote Rule
        res_remote = self.client.post("/api/rules/test", {
            "country": "India",
            "work_mode": "Remote",
            "exp_min": 3
        }, format="json")
        self.assertEqual(res_remote.status_code, status.HTTP_200_OK)
        self.assertEqual(res_remote.data["vault"], "Remote")

    def test_export_csv_and_excel(self):
        shot = Screenshot.objects.create(filename="test.jpg", original_name="test.jpg")
        Job.objects.create(
            screenshot=shot,
            title="Senior Architect",
            company="Skyline Design",
            location="Dehradun",
            status="synced",
            vault="India · Senior"
        )

        # CSV export
        res_csv = self.client.get("/api/export.csv")
        self.assertEqual(res_csv.status_code, status.HTTP_200_OK)
        self.assertEqual(res_csv["Content-Type"], "text/csv")
        self.assertIn(b"Senior Architect", res_csv.content)

        # Excel export
        res_xlsx = self.client.get("/api/export.xlsx")
        self.assertEqual(res_xlsx.status_code, status.HTTP_200_OK)
        self.assertIn("application/vnd.openxmlformats", res_xlsx["Content-Type"])

    def test_simple_login_and_auth(self):
        login_res = self.client.post("/api/auth/login", {
            "username": "adminuser",
            "password": "SecurePassword123!"
        }, format="json")
        self.assertEqual(login_res.status_code, status.HTTP_200_OK)
        self.assertTrue(login_res.data["success"])
        self.assertIn("tokens", login_res.data)

        # Profile with Bearer
        token = login_res.data["tokens"]["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        me_res = self.client.get("/api/auth/me")
        self.assertEqual(me_res.status_code, status.HTTP_200_OK)
        self.assertEqual(me_res.data["username"], "adminuser")
