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
            vault="Early Career Access Vault"
        )

        # List all
        res = self.client.get("/api/jobs")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(any(j["title"] == "Python Developer" for j in res.data["items"]))

        # Filter by search
        res_search = self.client.get("/api/jobs?q=Python")
        self.assertEqual(len(res_search.data["items"]), 1)

        # Filter by vault
        res_vault = self.client.get("/api/jobs?vault=Early Career Access Vault")
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
        self.assertEqual(res_rule.data["vault"], "Early Career Access Vault")

        # Test Remote Rule (Multi-vault: Remote + Experience tier)
        res_remote = self.client.post("/api/rules/test", {
            "country": "India",
            "work_mode": "Remote",
            "exp_min": 3
        }, format="json")
        self.assertEqual(res_remote.status_code, status.HTTP_200_OK)
        self.assertIn("Remote Access Vault", res_remote.data["vault"])
        self.assertIn("Early Career Access Vault", res_remote.data["vault"])

        # Test UAE / Dubai Global Rule (Even if salary is in LPA, Dubai/UAE jobs belong strictly to Global, not India tiers)
        res_uae = self.client.post("/api/rules/test", {
            "country": "UAE",
            "location": "Dubai",
            "exp_min": 12,
            "salary": "Up to ₹80–90 LPA, based on experience"
        }, format="json")
        self.assertEqual(res_uae.status_code, status.HTTP_200_OK)
        self.assertEqual(res_uae.data["vault"], "UAE & Global Access Vault")
        self.assertNotIn("Leadership Access Vault", res_uae.data["vault"])

        # Test Global Remote with USD salary (Multi-vault: Remote + Global)
        res_global_remote = self.client.post("/api/rules/test", {
            "country": "USA",
            "work_mode": "Remote",
            "salary": "$130,000–$160,000/year"
        }, format="json")
        self.assertEqual(res_global_remote.status_code, status.HTTP_200_OK)
        self.assertIn("Remote Access Vault", res_global_remote.data["vault"])
        self.assertIn("UAE & Global Access Vault", res_global_remote.data["vault"])

    def test_export_csv_and_excel(self):
        shot = Screenshot.objects.create(filename="test.jpg", original_name="test.jpg")
        Job.objects.create(
            screenshot=shot,
            title="Senior Architect",
            company="Skyline Design",
            location="Dehradun",
            status="synced",
            vault="Leadership Access Vault"
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

        import io
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(res_xlsx.content))
        self.assertIn("All Jobs", wb.sheetnames)
        self.assertIn("Leadership Access Vault", wb.sheetnames)

        # 1. Add new custom vault 'saari'
        add_res = self.client.post("/api/vaults", {
            "name": "saari",
            "min_exp": 1.0,
            "max_exp": 3.0,
            "description": "Custom saari vault"
        }, format="json")
        self.assertEqual(add_res.status_code, status.HTTP_201_CREATED)

        # Excel export now includes 'saari' tab
        res_xlsx_new = self.client.get("/api/export.xlsx")
        wb_new = openpyxl.load_workbook(io.BytesIO(res_xlsx_new.content))
        self.assertIn("saari", wb_new.sheetnames)

        # 2. Delete vault 'saari'
        del_res = self.client.delete("/api/vaults", {"name": "saari"}, format="json")
        self.assertEqual(del_res.status_code, status.HTTP_200_OK)

        # Excel export now removes 'saari' tab
        res_xlsx_del = self.client.get("/api/export.xlsx")
        wb_del = openpyxl.load_workbook(io.BytesIO(res_xlsx_del.content))
        self.assertNotIn("saari", wb_del.sheetnames)

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

    def test_generate_social_content(self):
        shot = Screenshot.objects.create(filename="shot1.jpg", original_name="shot1.jpg", raw_text="Full Stack Python Developer at TechNova")
        job = Job.objects.create(
            screenshot=shot,
            job_id="M-161126-01",
            title="Full Stack Python Developer",
            company="TechNova Solutions",
            location="Bengaluru",
            work_mode="Hybrid",
            exp_min=2.0,
            exp_max=4.0,
            salary="12-18 LPA",
            apply_contact="careers@technova.io",
            status="synced",
            vault="Early Career Access Vault"
        )
        res = self.client.post(f"/api/jobs/{job.id}/generate-content", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["ok"])
        self.assertIn("linkedin", res.data["content"])
        self.assertIn("instagram", res.data["content"])
        self.assertIn("TechNova Solutions", res.data["content"]["linkedin"])
        self.assertIn("TechNova Solutions", res.data["content"]["instagram"])

    def test_forgot_and_reset_password_flow(self):
        # 1. Request forgot password
        forgot_res = self.client.post("/api/auth/forgot-password", {
            "email": "admin@jobvault.ai"
        }, format="json")
        self.assertEqual(forgot_res.status_code, status.HTTP_200_OK)
        self.assertTrue(forgot_res.data["success"])
        data = forgot_res.data["data"]
        uidb64 = data["uidb64"]
        token = data["token"]
        otp = data["otp"]

        # 2. Verify token
        verify_token_res = self.client.post("/api/auth/verify-reset-token", {
            "uidb64": uidb64,
            "token": token
        }, format="json")
        self.assertEqual(verify_token_res.status_code, status.HTTP_200_OK)
        self.assertTrue(verify_token_res.data["valid"])

        # 3. Verify OTP
        verify_otp_res = self.client.post("/api/auth/verify-reset-token", {
            "email": "admin@jobvault.ai",
            "otp": otp
        }, format="json")
        self.assertEqual(verify_otp_res.status_code, status.HTTP_200_OK)
        self.assertTrue(verify_otp_res.data["valid"])

        # 4. Reset password using token
        new_pass = "BrandNewSecretPassword99!"
        reset_res = self.client.post("/api/auth/reset-password", {
            "uidb64": uidb64,
            "token": token,
            "new_password": new_pass,
            "confirm_new_password": new_pass
        }, format="json")
        self.assertEqual(reset_res.status_code, status.HTTP_200_OK)
        self.assertTrue(reset_res.data["success"])

        # 5. Verify old password fails
        old_login = self.client.post("/api/auth/login", {
            "username": "adminuser",
            "password": "SecurePassword123!"
        }, format="json")
        self.assertEqual(old_login.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(old_login.data["error"], "Invalid username or password.")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password(new_pass))
        self.assertFalse(self.admin.check_password("SecurePassword123!"))

        # 6. Verify new password succeeds
        new_login = self.client.post("/api/auth/login", {
            "username": "adminuser",
            "password": new_pass
        }, format="json")
        self.assertEqual(new_login.status_code, status.HTTP_200_OK)
        self.assertTrue(new_login.data["success"])

    def test_all_three_upload_cases(self):
        from PIL import Image

        def make_test_img(text="Test"):
            im = Image.new("RGB", (300, 200), color=(240, 240, 240))
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()

        # CASE 1: Single screenshot upload -> 1 job
        img1 = SimpleUploadedFile("single_job.png", make_test_img("Single"), content_type="image/png")
        res_case1 = self.client.post("/api/screenshots", {"files": [img1]}, format="multipart")
        self.assertEqual(res_case1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(res_case1.data["ids"]), 1)

        # CASE 2: Batch upload (multiple distinct jobs) -> separate jobs
        img_a = SimpleUploadedFile("batch_job1.png", make_test_img("Job A"), content_type="image/png")
        img_b = SimpleUploadedFile("batch_job2.png", make_test_img("Job B"), content_type="image/png")
        res_case2 = self.client.post("/api/screenshots", {"files": [img_a, img_b], "combine": "false"}, format="multipart")
        self.assertEqual(res_case2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(res_case2.data["ids"]), 2)
        self.assertFalse(res_case2.data.get("combined", False))

        # CASE 3: Multi-part upload of 1 job (1 to 4 screenshots) -> 1 consolidated job
        part1 = SimpleUploadedFile("job_part1.png", make_test_img("Header"), content_type="image/png")
        part2 = SimpleUploadedFile("job_part2.png", make_test_img("Skills"), content_type="image/png")
        part3 = SimpleUploadedFile("job_part3.png", make_test_img("Contact"), content_type="image/png")
        res_case3 = self.client.post("/api/screenshots", {"files": [part1, part2, part3], "combine": "true"}, format="multipart")
        self.assertEqual(res_case3.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(res_case3.data["ids"]), 1)
        self.assertTrue(res_case3.data.get("combined"))
        self.assertEqual(res_case3.data.get("parts_count"), 3)


