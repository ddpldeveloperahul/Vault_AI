# Generated manually to reclassify jobs with updated global and tier logic

from django.db import migrations


def reclassify_all_jobs(apps, schema_editor):
    from myapp.utils import classify_job, get_expected_job_id_prefix, generate_job_id
    Job = apps.get_model("myapp", "Job")

    for job in Job.objects.all():
        job_data = {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "country": job.country,
            "exp_min": job.exp_min,
            "exp_max": job.exp_max,
            "salary": job.salary,
            "work_mode": job.work_mode,
            "other_details": job.other_details,
            "evidence": job.evidence,
        }
        new_vault = classify_job(job_data)
        if job.vault != new_vault:
            job.vault = new_vault

        expected_prefix = get_expected_job_id_prefix(job.vault, job.work_mode)
        if not job.job_id or job.job_id[0] != expected_prefix:
            date_val = job.created_at.date() if job.created_at else None
            job.job_id = generate_job_id(job.vault, date_obj=date_val, work_mode=job.work_mode)
        job.save()


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0005_alter_job_vault"),
    ]

    operations = [
        migrations.RunPython(reclassify_all_jobs, reverse_code=migrations.RunPython.noop),
    ]
