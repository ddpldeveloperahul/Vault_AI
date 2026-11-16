from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from myapp.models import Screenshot, Job, User, ActivityLog
from myapp.utils import SAMPLE_EXTRACTIONS, classify_job, calculate_fingerprint, get_vault_rules


class Command(BaseCommand):
    help = "Seed initial demo screenshots and jobs"

    def handle(self, *args, **options):
        # Create default admin if not exists
        admin_user, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@jobvault.ai",
                "first_name": "JobVault",
                "last_name": "Admin",
                "role": "ADMIN",
                "is_staff": True,
                "is_superuser": True,
            }
        )
        if created:
            admin_user.set_password("rahul")
            admin_user.save()
            self.stdout.write(self.style.SUCCESS("Created default admin user: admin / rahul"))

        now = timezone.now()
        demo_jobs = [
            {
                "filename": "IMG-20261106-WA0191.jpg",
                "app": "WhatsApp",
                "title": "Accounts Assistant",
                "company": "Doon Valley Traders",
                "location": "Dehradun",
                "country": "India",
                "exp_min": 1.0,
                "exp_max": 2.0,
                "salary": "2.4 - 3 LPA",
                "work_mode": "Onsite",
                "apply_contact": "72xxxx1180",
                "confidence": 0.93,
                "status": "synced",
                "evidence": {
                    "title": "Accounts Assistant",
                    "company": "Doon Valley Traders",
                    "location": "Dehradun",
                    "exp": "Exp: 1-2 yrs",
                    "salary": "Salary 2.4 - 3 LPA",
                    "apply_contact": "Call 72xxxx1180"
                },
                "raw_text": "*Vacancy*\nAccounts Assistant\nDoon Valley Traders, Dehradun\nExp: 1-2 yrs (Tally)\nSalary 2.4 - 3 LPA\nCall 72xxxx1180"
            },
            {
                "filename": "IMG-20261105-WA0184.jpg",
                "app": "WhatsApp",
                "title": "Operations Executive",
                "company": "Tarang Foods",
                "location": "Haridwar",
                "country": "India",
                "exp_min": 1.0,
                "exp_max": 3.0,
                "salary": None,
                "work_mode": None,
                "apply_contact": "jobs@tarangfoods.in",
                "confidence": 0.72,
                "status": "review",
                "evidence": {
                    "title": "Operations Executive",
                    "company": "Tarang Foods",
                    "location": "Haridwar",
                    "exp": "Exp: 1-3 yrs",
                    "apply_contact": "jobs@tarangfoods.in"
                },
                "raw_text": "*Hiring*\nOperations Executive\nTarang Foods, Haridwar\nExp: 1-3 yrs\nCTC: 3.5\njobs@tarangfoods.in"
            },
            {
                "filename": "IMG-20261104-WA0177.jpg",
                "app": "LinkedIn",
                "title": "Senior Data Analyst",
                "company": "Northwind Analytics",
                "location": "Bengaluru",
                "country": "India",
                "exp_min": 5.0,
                "exp_max": 8.0,
                "salary": "₹18–24 LPA",
                "work_mode": "Hybrid",
                "apply_contact": "careers.northwind.in/da-114",
                "confidence": 0.96,
                "status": "synced",
                "evidence": {
                    "title": "Senior Data Analyst",
                    "company": "Northwind Analytics",
                    "location": "Bengaluru",
                    "exp": "5-8 years",
                    "salary": "₹18–24 LPA",
                    "work_mode": "Hybrid",
                    "apply_contact": "careers.northwind.in/da-114"
                },
                "raw_text": "Northwind Analytics is hiring!\nRole: Senior Data Analyst\nLocation: Bengaluru (Hybrid)\nExperience: 5-8 years\nCTC: ₹18–24 LPA\nApply: careers.northwind.in/da-114"
            },
            {
                "filename": "IMG-20261103-WA0170.jpg",
                "app": "Instagram",
                "title": "Content Writer",
                "company": "Digital Media",
                "location": "Mumbai",
                "country": "India",
                "exp_min": 0.0,
                "exp_max": None,
                "salary": None,
                "work_mode": None,
                "apply_contact": "link in bio",
                "confidence": 0.60,
                "status": "review",
                "evidence": {
                    "title": "Content Writer",
                    "exp": "Freshers welcome",
                    "apply_contact": "link in bio"
                },
                "raw_text": "WE ARE HIRING\nContent Writer\nFreshers welcome!!\nSend CV - link in bio"
            },
            {
                "filename": "IMG-20261102-WA0163.jpg",
                "app": "Telegram",
                "title": "Frontend Developer (React)",
                "company": "Lumen Stack",
                "location": "Remote",
                "country": None,
                "exp_min": 2.0,
                "exp_max": 4.0,
                "salary": "$40-55k / yr",
                "work_mode": "Remote",
                "apply_contact": "lumenstack.io/jobs/fe",
                "confidence": 0.93,
                "status": "synced",
                "evidence": {
                    "title": "Frontend Developer (React)",
                    "company": "Lumen Stack",
                    "location": "Remote",
                    "exp": "2-4 yrs experience",
                    "salary": "$40-55k / yr",
                    "work_mode": "Remote",
                    "apply_contact": "lumenstack.io/jobs/fe"
                },
                "raw_text": "Frontend Developer (React)\nLumen Stack · Remote, work from anywhere\n2-4 yrs experience\n$40-55k / yr\nlumenstack.io/jobs/fe"
            },
        ]

        rules = get_vault_rules()
        created_count = 0
        for i, item in enumerate(demo_jobs):
            shot, _ = Screenshot.objects.get_or_create(
                original_name=item["filename"],
                defaults={
                    "filename": item["filename"],
                    "origin": "upload",
                    "source_app": item["app"],
                    "stage": "saved",
                    "raw_text": item["raw_text"],
                    "created_at": now - timedelta(days=i),
                    "processed_at": now - timedelta(days=i),
                }
            )

            job_dict = {
                "title": item["title"],
                "company": item["company"],
                "location": item["location"],
                "country": item["country"],
                "exp_min": item["exp_min"],
                "exp_max": item["exp_max"],
                "salary": item["salary"],
                "work_mode": item["work_mode"],
                "apply_contact": item["apply_contact"],
            }
            vault = classify_job(job_dict, rules)
            fp = calculate_fingerprint(job_dict)

            job, j_created = Job.objects.get_or_create(
                screenshot=shot,
                title=item["title"],
                defaults={
                    "company": item["company"],
                    "location": item["location"],
                    "country": item["country"],
                    "exp_min": item["exp_min"],
                    "exp_max": item["exp_max"],
                    "salary": item["salary"],
                    "work_mode": item["work_mode"],
                    "apply_contact": item["apply_contact"],
                    "source_app": item["app"],
                    "vault": vault,
                    "confidence": item["confidence"],
                    "evidence": item["evidence"],
                    "flags": [] if item["status"] == "synced" else ["salary", "work_mode"],
                    "status": item["status"],
                    "fingerprint": fp,
                    "created_at": now - timedelta(days=i),
                }
            )
            if j_created:
                created_count += 1
                ActivityLog.objects.create(
                    action="Sorter" if job.status == "synced" else "Verification",
                    details=f"JV-{job.id} {job.title} → {job.vault}"
                )

        self.stdout.write(self.style.SUCCESS(f"Seeded {created_count} demo jobs into PostgreSQL Vault_AI."))

