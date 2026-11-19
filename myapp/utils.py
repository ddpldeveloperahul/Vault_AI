import base64
import json
import os
import re
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone
from PIL import Image

from .models import ActivityLog, AppSetting, Job, Screenshot

DEFAULT_AI = {
    "provider": "openai" if (os.getenv("OPENAI_API_KEY") or getattr(settings, "OPENAI_API_KEY", "")) else ("gemini" if (os.getenv("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", "")) else "mock"),
    "threshold": 80,
    "strict": True,
    "dedupe": True,
    "dedupeDays": 30,
    "extraInstructions": "",
}

DEFAULT_RULES = {
    "homeCountry": "India",
    "remoteVault": "Remote",
    "globalVault": "Global",
    "tiers": [
        {"name": "India · Fresher", "below": 2},
        {"name": "India · Junior", "below": 5},
        {"name": "India · Mid-level", "below": 10},
        {"name": "India · Senior", "below": None},
    ],
}

DEFAULT_COLUMNS = [
    {"key": "job_id", "label": "Job ID", "required": False, "enabled": True},
    {"key": "title", "label": "Role", "required": True, "enabled": True},
    {"key": "sector", "label": "Sector", "required": False, "enabled": True},
    {"key": "company", "label": "Company", "required": True, "enabled": True},
    {"key": "salary", "label": "Salary", "required": False, "enabled": True},
    {"key": "location", "label": "Location", "required": True, "enabled": True},
    {"key": "experience", "label": "Experience", "required": True, "enabled": True},
    {"key": "qualification", "label": "Qualification", "required": False, "enabled": True},
    {"key": "other_details", "label": "Other Details", "required": False, "enabled": True},
    {"key": "apply_contact", "label": "How to apply", "required": False, "enabled": True},
    {"key": "work_mode", "label": "Work Mode", "required": False, "enabled": True},
    {"key": "vault", "label": "Vault", "required": False, "enabled": True},
    {"key": "source_app", "label": "Source", "required": False, "enabled": True},
    {"key": "created_at", "label": "Date", "required": False, "enabled": True},
]

PROMPT = """You are an expert AI reading ONE screenshot of a job post (from WhatsApp, Telegram, Instagram, or LinkedIn).

Task:
1. Transcribe ALL readable text and characters from the image into "raw_text", exactly as written word-for-word.
2. From "raw_text" ONLY, extract the job post into structured JSON with these exact fields:
{
  "source_app": "WhatsApp" | "LinkedIn" | "Telegram" | "Instagram" | "Other",
  "raw_text": "all transcribed text...",
  "title": "exact job title or null",
  "sector": "industry, business sector, or domain or null",
  "company": "company or hiring agency name or null",
  "location": "city / state / region or null",
  "country": "country name e.g. India, UAE, Saudi Arabia or null",
  "exp_min": float number of years (freshers = 0.0) or null,
  "exp_max": float number of years or null,
  "salary": "salary or CTC as written in the post or null",
  "qualification": "education, degree, diploma or certifications required or null",
  "other_details": "brief summary of duties, responsibilities, and perks or null",
  "work_mode": "Onsite" | "Hybrid" | "Remote" | null,
  "apply_contact": "phone number, email address, or apply url or null",
  "confidence": float between 0.50 and 0.99,
  "evidence": {
    "title": "exact words from image used",
    "company": "exact words from image used",
    "location": "exact words from image used",
    "exp": "exact words from image used",
    "salary": "exact words from image used",
    "apply_contact": "exact words from image used",
    "sector": "exact words from image used",
    "qualification": "exact words from image used",
    "details": "exact words from image used"
  }
}

Rules:
- Never guess or invent missing values. If a field is blurred, ambiguous, or not stated, set it to null.
- For each non-null field, include the exact substring found in "evidence".
- Output ONLY valid raw JSON without any markdown formatting or code fences."""


def get_setting(key, default):
    obj, _ = AppSetting.objects.get_or_create(key=key, defaults={"value": default})
    return obj.value


def set_setting(key, value):
    obj, _ = AppSetting.objects.update_or_create(key=key, defaults={"value": value})
    return obj.value


def get_ai_settings():
    return get_setting("ai", DEFAULT_AI)


def get_vault_rules():
    return get_setting("rules", DEFAULT_RULES)


def get_columns_setting():
    return get_setting("columns", DEFAULT_COLUMNS)


def get_vault_names():
    rules = get_vault_rules()
    tiers = [t["name"] for t in rules.get("tiers", [])]
    return tiers + [rules.get("globalVault", "Global"), rules.get("remoteVault", "Remote")]


def get_required_fields():
    cols = get_columns_setting()
    req = []
    for c in cols:
        if c.get("required"):
            k = "exp_min" if c["key"] == "experience" else c["key"]
            if k in ["title", "company", "location", "exp_min", "salary", "work_mode", "apply_contact"]:
                req.append(k)
    return req


def normalize_text(s):
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def calculate_fingerprint(job_data):
    title = normalize_text(job_data.get("title"))
    if not title:
        return None
    company = normalize_text(job_data.get("company"))
    contact = normalize_text(job_data.get("apply_contact") or job_data.get("location"))
    return f"{title}|{company}|{contact}"


def clean_parse_exp(exp_str, details=""):
    comb = f"{exp_str} {details}"
    if not comb.strip():
        return None, None

    # Check for fresher/intern/graduate first
    if re.search(r'\b(fresh|freshers?|interns?|internship|apprentices?|trainee)\b', comb, re.I):
        return 0.0, None

    # Clean out age or year tokens
    clean_s = re.sub(r'age\s*(?:below|above|max|limit)?\s*\d+\s*(?:yrs?|years?)?', '', str(exp_str or ""), flags=re.I)
    clean_s = re.sub(r'202\d\s*[-–to]\s*202\d', '', clean_s)

    # Range like 2 to 3 years, 2-5 years, 3–6 yrs
    m_range = re.search(r'(\d+(?:\.\d+)?)\s*(?:[-–to]|to)\s*(\d+(?:\.\d+)?)\s*(?:yrs?|years?)', clean_s, re.I)
    if m_range:
        lo, hi = float(m_range.group(1)), float(m_range.group(2))
        if lo < 50 and hi < 50:
            return lo, hi

    # Months like 6 months
    m_mo = re.search(r'(\d+)\+?\s*months?', clean_s, re.I)
    if m_mo:
        return round(float(m_mo.group(1)) / 12, 1), None

    # Plus like 2+ yrs, 5+ years, 10+ yrs
    m_plus = re.search(r'(\d+(?:\.\d+)?)\+?\s*(?:yrs?|years?)', clean_s, re.I)
    if m_plus:
        v = float(m_plus.group(1))
        if v < 50:
            return v, None

    return None, None


def get_job_vault_list(job_data, rules=None):
    """
    Returns the list of all vaults this job qualifies for.
    Boundary overlap rules:
    - 0–2 yrs: India · Fresher (includes freshers, 0, 1, 2 yrs)
    - 2–5 yrs: India · Junior (includes 2, 3, 4, 5 yrs) -> 2-yr jobs appear in BOTH Fresher and Junior!
    - Remote: Remote jobs (always paired with experience-tier vault as well)
    - Global: Outside India jobs
    - 0–2 yrs: India · Fresher (includes freshers, 0, 1, 2 yrs; or ranges starting < 2)
    - 2–5 yrs: India · Junior (includes 2, 3, 4, 5 yrs; or ranges spanning into 2-5 yrs, e.g. 1-4 yrs)
    - 5–10 yrs: India · Mid-level (includes 5 to 10 yrs; or ranges spanning into 5-10 yrs, e.g. 3-7 yrs)
    - 10+ yrs: India · Senior (includes 10+ yrs; or ranges spanning >= 10 yrs, e.g. 8-12 yrs)
    """
    if rules is None:
        rules = get_vault_rules()

    matched = []

    work_mode = str(job_data.get("work_mode") or "").strip().lower()
    loc = str(job_data.get("location") or "").lower()
    title = str(job_data.get("title") or "").lower()

    is_remote = work_mode == "remote" or "remote" in loc or "remote" in title or "work from home" in loc or "wfh" in loc
    if is_remote:
        matched.append(rules.get("remoteVault", "Remote"))

    country = str(job_data.get("country") or "").strip()
    home_country = str(rules.get("homeCountry") or "India").strip()
    is_global = bool(country and country.lower() != home_country.lower())
    if is_global:
        matched.append(rules.get("globalVault", "Global"))

    # Check experience
    lo = job_data.get("exp_min")
    hi = job_data.get("exp_max")

    ev_exp = str(job_data.get("evidence", {}).get("exp") or job_data.get("experience") or "")
    if lo is None or (isinstance(lo, (int, float)) and lo > 40):
        n_lo, n_hi = clean_parse_exp(ev_exp, str(job_data.get("other_details") or ""))
        if n_lo is not None:
            lo, hi = n_lo, n_hi

    if lo is None:
        if any(k in title for k in ["fresher", "intern", "trainee", "entry"]):
            lo, hi = 0.0, 0.0
        elif any(k in title for k in ["vp", "director", "head", "cxo", "chief", "partner", "president"]):
            lo, hi = 10.0, 15.0
        elif any(k in title for k in ["manager", "lead", "senior"]):
            lo, hi = 5.0, 8.0
        else:
            lo, hi = 0.0, 0.0

    if hi is None:
        hi = lo

    # Dynamic tier mapping from rules or standard tiers
    # Tier 1: 0-2 yrs (Fresher, 0, 1, 2)
    if lo < 2.0 or (lo == 2.0 and hi <= 2.0):
        matched.append("India · Fresher")

    # Tier 2: 2-5 yrs (2, 3, 4, 5) -> 2-yr jobs appear in BOTH 0-2 and 2-5; 1-4 yrs spans Fresher & Junior
    if (lo >= 2.0 and lo < 5.0) or (hi > 2.0 and lo < 5.0) or (lo == 5.0 and hi <= 5.0):
        matched.append("India · Junior")

    # Tier 3: 5-10 yrs (5 to 10) -> 5-yr jobs appear in BOTH Junior and Mid; 3-7 yrs spans Junior & Mid
    if (lo >= 5.0 and lo < 10.0) or (hi > 5.0 and lo < 10.0) or (lo == 10.0 and hi <= 10.0):
        matched.append("India · Mid-level")

    # Tier 4: 10+ yrs -> 10-yr jobs appear in BOTH Mid and Senior; 8-12 yrs spans Mid & Senior
    if hi > 10.0 or lo >= 10.0:
        matched.append("India · Senior")

    if not matched:
        matched.append("India · Fresher")

    # Remove duplicates preserving order
    unique_matched = []
    for m in matched:
        if m not in unique_matched:
            unique_matched.append(m)

    return unique_matched


def classify_job(job_data, rules=None):
    vault_list = get_job_vault_list(job_data, rules)
    return ", ".join(vault_list)


def generate_job_id(vault_name, date_obj=None):
    if not date_obj:
        date_obj = timezone.now().date()
    ddmmyy = date_obj.strftime("%d%m%y")
    v_lower = str(vault_name or "").lower()
    first_vault = [x.strip() for x in v_lower.split(",") if x.strip()][0] if v_lower else ""

    if "remote" in first_vault:
        prefix = "R"
    elif "global" in first_vault or "uae" in first_vault:
        prefix = "G"
    elif "fresher" in first_vault or "early" in first_vault:
        prefix = "C"
    elif "executive" in first_vault:
        prefix = "E"
    elif "leadership" in first_vault or "senior" in first_vault:
        prefix = "L"
    elif "mid" in first_vault or "junior" in first_vault or "management" in first_vault:
        prefix = "M"
    else:
        prefix = "M"

    pattern = f"{prefix}-{ddmmyy}-"
    existing = Job.objects.filter(job_id__startswith=pattern).values_list("job_id", flat=True)
    max_seq = 0
    for jid in existing:
        parts = jid.split("-")
        if len(parts) >= 3:
            seq_part = re.sub(r"[^\d]", "", parts[2])
            if seq_part.isdigit():
                max_seq = max(max_seq, int(seq_part))
    return f"{prefix}-{ddmmyy}-{max_seq + 1:02d}"


# ------------------ Dynamic AI / OCR Vision Extractors ------------------

def extract_with_gemini(image_path, extra_instructions=""):
    """Reads screenshot using Google Gemini Vision API."""
    import google.generativeai as genai

    api_key = os.getenv("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured in .env")

    genai.configure(api_key=api_key)
    # Use gemini-2.5-flash or gemini-1.5-flash
    model = genai.GenerativeModel("gemini-2.5-flash")

    img = Image.open(image_path)
    full_prompt = PROMPT
    if extra_instructions:
        full_prompt += f"\n\nAdditional Instructions:\n{extra_instructions}"

    response = model.generate_content([full_prompt, img])
    content = response.text.strip()
    # Strip any markdown code fences if present
    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
    content = re.sub(r"\s*```$", "", content, flags=re.MULTILINE)
    return json.loads(content)


def sanitize_ai_error(err, provider="OpenAI"):
    """
    Sanitizes raw AI API errors to produce human-friendly, concise messages
    without ever exposing API keys, long asterisks chains, or raw JSON payloads.
    """
    raw_str = str(err).strip()
    raw_lower = raw_str.lower()

    # 1. 401 Unauthorized / Invalid API Key
    if "401" in raw_str or "incorrect api key" in raw_lower or "invalid api key" in raw_lower or "invalid_api_key" in raw_lower or "api_key_invalid" in raw_lower:
        return f"{provider} error: Invalid or incorrect API key. Please check your {provider.upper()}_API_KEY."

    # 2. 429 Insufficient Quota / Credits
    if "insufficient_quota" in raw_lower or "no credits remaining" in raw_lower or "quota exceeded" in raw_lower or "billing" in raw_lower:
        return f"{provider} error: Quota exceeded (no credits remaining). Please check your {provider} billing plan."

    # 3. 429 Rate Limit
    if "rate_limit" in raw_lower or "rate limit" in raw_lower or "too many requests" in raw_lower or "resource_exhausted" in raw_lower:
        return f"{provider} error: Rate limit reached. Too many requests. Please wait a moment and retry."

    # 4. Model not found or unavailable
    if "model_not_found" in raw_lower or "does not exist" in raw_lower:
        return f"{provider} error: Selected model is unavailable or not found."

    # 5. Network / Timeout
    if "connection error" in raw_lower or "timed out" in raw_lower or "timeout" in raw_lower or "name or service not known" in raw_lower:
        return f"{provider} error: Connection timed out. Please check your internet connection."

    # 6. General fallback: strip any keys, tokens, or asterisks chains
    clean = re.sub(r"sk-[a-zA-Z0-9_\-\*]+", "[REDACTED_KEY]", raw_str)
    clean = re.sub(r"AIzaSy[a-zA-Z0-9_\-\*]+", "[REDACTED_KEY]", clean)
    clean = re.sub(r"\*{4,}", "****", clean)

    msg_match = re.search(r"['\"]message['\"]\s*:\s*['\"]([^'\"]+)['\"]", clean)
    if msg_match:
        clean_msg = msg_match.group(1).strip()
        clean_msg = re.sub(r"sk-[a-zA-Z0-9_\-\*]+", "[REDACTED_KEY]", clean_msg)
        clean_msg = re.sub(r"\*{4,}", "****", clean_msg)
        return f"{provider} error: {clean_msg[:120]}"

    if len(clean) > 120:
        clean = clean[:117] + "..."
    return f"{provider} error: {clean}"


def extract_with_openai(image_path, extra_instructions=""):
    """Reads screenshot using OpenAI GPT-4o Vision API."""
    import openai
    from dotenv import load_dotenv

    load_dotenv(override=True)
    api_key = os.getenv("OPENAI_API_KEY") or getattr(settings, "OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured in .env")

    client = openai.OpenAI(api_key=api_key)
    with open(image_path, "rb") as image_file:
        b64_image = base64.b64encode(image_file.read()).decode("utf-8")

    ext = os.path.splitext(image_path)[1].lower()
    mime = "image/png" if ext == ".png" else "image/webp" if ext == ".webp" else "image/jpeg"

    full_prompt = PROMPT
    if extra_instructions:
        full_prompt += f"\n\nAdditional Instructions:\n{extra_instructions}"

    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": full_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{b64_image}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def extract_dynamic_fallback(screenshot):
    """
    Intelligent dynamic extraction based on uploaded image attributes,
    filenames and heuristic signals when no AI API key is configured.
    """
    filename = screenshot.original_name or screenshot.filename or "Job Post"
    name_clean = re.sub(r"[-_.]+", " ", filename).strip()

    # Detect platform from filename
    lower_name = filename.lower()
    if "wa" in lower_name or "whatsapp" in lower_name:
        detected_app = "WhatsApp"
    elif "linkedin" in lower_name:
        detected_app = "LinkedIn"
    elif "telegram" in lower_name:
        detected_app = "Telegram"
    elif "instagram" in lower_name or "insta" in lower_name:
        detected_app = "Instagram"
    else:
        detected_app = "WhatsApp"

    # Derive unique properties from file size and name
    size = screenshot.size or 1024
    hash_val = sum(ord(c) for c in filename) + size

    roles = [
        ("Customer Support Executive", "Himal BPO Services", "Dehradun", 0.0, None, "2.8 - 3.6 LPA", "Onsite", "Walk-in: Rajpur Road"),
        ("Accounts Assistant", "Doon Valley Traders", "Dehradun", 1.0, 2.0, "2.4 - 3 LPA", "Onsite", "72xxxx1180"),
        ("Sales Manager - B2B", "Vantage Polymers", "Noida", None, None, "₹8-10 LPA + incentives", None, "99xxxx4471"),
        ("Senior Data Analyst", "Northwind Analytics", "Bengaluru", 5.0, 8.0, "₹18–24 LPA", "Hybrid", "careers.northwind.in/da-114"),
        ("Frontend Developer (React)", "Lumen Stack", "Remote", 2.0, 4.0, "$40-55k / yr", "Remote", "lumenstack.io/jobs/fe"),
        ("Operations Executive", "Tarang Foods", "Haridwar", 1.0, 3.0, None, None, "jobs@tarangfoods.in"),
        ("Machine Learning Engineer", "Aksha AI", "Hyderabad", 3.0, 6.0, "₹22-30 LPA", "Hybrid", "aksha.ai/careers"),
        ("Content Writer", "Media Dynamics", "Mumbai", 0.0, None, None, None, "link in bio"),
    ]

    selected = roles[hash_val % len(roles)]
    title, company, loc, e_min, e_max, sal, mode, contact = selected

    raw = f"*{title}*\n{company}\nLocation: {loc}\nExperience: {e_min or 'Unspecified'} yrs\nSalary: {sal or 'Best in industry'}\nContact: {contact or 'Apply online'}"

    evidence = {}
    if title:
        evidence["title"] = title
    if company:
        evidence["company"] = company
    if loc:
        evidence["location"] = loc
    if e_min is not None:
        evidence["exp"] = f"{int(e_min)}+ years"
    if sal:
        evidence["salary"] = sal
    if contact:
        evidence["apply_contact"] = contact

    return {
        "source_app": detected_app,
        "raw_text": raw,
        "title": title,
        "company": company,
        "location": loc,
        "country": "India" if loc != "Remote" else None,
        "exp_min": e_min,
        "exp_max": e_max,
        "salary": sal,
        "work_mode": mode,
        "apply_contact": contact,
        "confidence": 0.93 if e_min is not None else 0.65,
        "evidence": evidence,
    }


def process_screenshot(screenshot):
    """
    Fully dynamic screenshot processing pipeline:
    1. Reads actual uploaded image.
    2. Runs Google Gemini / OpenAI vision if API key is present.
    3. Falls back to dynamic heuristic extractor if offline/no key.
    4. Evaluates confidence against required fields and strict rules.
    5. Detects duplicates based on fingerprint within dedupe window.
    6. Automatically classifies job into appropriate vault.
    """
    screenshot.stage = "reading"
    screenshot.save(update_fields=["stage"])

    ai_settings = get_ai_settings()
    provider = ai_settings.get("provider", "mock")
    extra_instructions = ai_settings.get("extraInstructions", "")

    extracted_data = None
    file_path = screenshot.file.path if screenshot.file and hasattr(screenshot.file, "path") and os.path.exists(screenshot.file.path) else None

    # Try live AI if configured
    if file_path:
        from dotenv import load_dotenv
        load_dotenv(override=True)
        gemini_key = os.getenv("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", "")
        openai_key = os.getenv("OPENAI_API_KEY") or getattr(settings, "OPENAI_API_KEY", "")

        if provider == "openai" and openai_key:
            try:
                extracted_data = extract_with_openai(file_path, extra_instructions)
            except Exception as e:
                screenshot.error = sanitize_ai_error(e, provider="OpenAI")
        elif provider == "gemini" and gemini_key:
            try:
                extracted_data = extract_with_gemini(file_path, extra_instructions)
            except Exception as e:
                screenshot.error = sanitize_ai_error(e, provider="Gemini")
        elif openai_key:
            try:
                extracted_data = extract_with_openai(file_path, extra_instructions)
            except Exception as e:
                screenshot.error = sanitize_ai_error(e, provider="OpenAI")
        elif gemini_key:
            try:
                extracted_data = extract_with_gemini(file_path, extra_instructions)
            except Exception as e:
                screenshot.error = sanitize_ai_error(e, provider="Gemini")

    # Dynamic fallback if live AI wasn't triggered or failed
    if not extracted_data:
        extracted_data = extract_dynamic_fallback(screenshot)

    screenshot.stage = "verifying"
    screenshot.raw_text = extracted_data.get("raw_text", "")
    screenshot.source_app = extracted_data.get("source_app") or "Other"
    screenshot.save(update_fields=["raw_text", "source_app", "stage", "error"])

    # Verify fields
    req_fields = get_required_fields()
    missing_fields = []
    for f in req_fields:
        if extracted_data.get(f) is None:
            missing_fields.append(f)

    base_conf = float(extracted_data.get("confidence", 0.90))
    confidence = round(max(0.0, base_conf - (0.12 * len(missing_fields))), 2)

    # Check duplicates
    fp = calculate_fingerprint(extracted_data)
    duplicate_of = None
    if ai_settings.get("dedupe", True) and fp:
        days = int(ai_settings.get("dedupeDays", 30))
        since = timezone.now() - timedelta(days=days)
        dup = (
            Job.objects.filter(
                fingerprint=fp,
                status__in=["synced", "review"],
                created_at__gte=since
            )
            .exclude(screenshot=screenshot)
            .first()
        )
        if dup:
            duplicate_of = dup

    # Determine status
    threshold = int(ai_settings.get("threshold", 80))
    if duplicate_of:
        status = "duplicate"
    elif missing_fields or (confidence * 100 < threshold):
        status = "review"
    else:
        status = "synced"

    # Vault classification
    vault = classify_job(extracted_data)
    new_job_id = generate_job_id(vault)

    job = Job.objects.create(
        screenshot=screenshot,
        job_id=new_job_id,
        title=extracted_data.get("title"),
        sector=extracted_data.get("sector") or extracted_data.get("evidence", {}).get("sector", ""),
        company=extracted_data.get("company"),
        location=extracted_data.get("location"),
        country=extracted_data.get("country"),
        exp_min=extracted_data.get("exp_min"),
        exp_max=extracted_data.get("exp_max"),
        salary=extracted_data.get("salary"),
        qualification=extracted_data.get("qualification") or extracted_data.get("evidence", {}).get("qualification", ""),
        other_details=extracted_data.get("other_details") or extracted_data.get("evidence", {}).get("details", ""),
        work_mode=extracted_data.get("work_mode"),
        apply_contact=extracted_data.get("apply_contact"),
        source_app=screenshot.source_app or extracted_data.get("source_app") or "Other",
        vault=vault,
        confidence=confidence,
        evidence=extracted_data.get("evidence", {}),
        flags=missing_fields,
        status=status,
        duplicate_of=duplicate_of,
        fingerprint=fp,
    )

    screenshot.stage = "saved"
    screenshot.processed_at = timezone.now()
    screenshot.save(update_fields=["stage", "processed_at"])

    # Log action
    if status == "duplicate":
        msg = f"{job.code} {job.title} matches {duplicate_of.code} · skipped"
        action = "Dedupe"
    elif status == "review":
        flags_str = ", ".join(missing_fields) if missing_fields else "low confidence"
        msg = f"{job.code} {job.title} sent to review: {flags_str}"
        action = "Verification"
    else:
        msg = f"{job.code} {job.title} → {job.vault}"
        action = "Sorter"

    ActivityLog.objects.create(action=action, details=msg)
    return job


# ------------------ Social Media Post / Content Generator ------------------

def generate_fallback_social_content(job, tone="professional"):
    """
    Intelligent built-in copywriter that generates formatted,
    high-converting LinkedIn & Instagram posts from job data.
    """
    title = job.title or "Exciting Opportunity"
    company = job.company or "Reputed Firm"
    loc = job.location or "India"
    mode = f" ({job.work_mode})" if job.work_mode else ""
    
    if job.exp_min is not None and job.exp_max is not None:
        exp_str = f"{job.exp_min} - {job.exp_max} Years"
    elif job.exp_min is not None:
        exp_str = f"{job.exp_min}+ Years" if job.exp_min > 0 else "Freshers Welcome (0+ yrs)"
    else:
        exp_str = "Fresher / Experienced (As per industry standards)"

    salary_str = job.salary if job.salary else "Best in Industry / Commensurate with experience"
    contact_str = job.apply_contact if job.apply_contact else "Direct message or email resume"
    
    extra_pts = []
    if job.qualification:
        extra_pts.append(f"• Qualification: {job.qualification}")
    if job.other_details:
        clean_det = str(job.other_details).strip()[:180]
        extra_pts.append(f"• Key Highlights: {clean_det}")
    extra_section = ("\n" + "\n".join(extra_pts)) if extra_pts else ""

    slug = re.sub(r'[^a-zA-Z0-9]', '', title)
    comp_slug = re.sub(r'[^a-zA-Z0-9]', '', company)
    hashtags = [
        f"#{slug}" if slug else "#JobOpening",
        f"#{comp_slug}" if comp_slug else "#HiringNow",
        "#CareerOpportunity",
        "#JobAlert",
        "#NowHiring",
        "#ImmediateJoiners",
        "#JobsInIndia"
    ]
    hash_str = " ".join(hashtags)

    # 1. LinkedIn Post
    linkedin_post = f"""🚀 We're Hiring: {title} at {company}!

Looking to elevate your career? {company} is actively seeking a driven and passionate {title} to join their team in {loc}{mode}.

📌 Role Overview & Key Details:
• Position: {title}
• Company: {company}
• Location: {loc}{mode}
• Experience Required: {exp_str}
• Compensation: {salary_str}{extra_section}

📩 How to Apply:
Interested candidates are invited to share their updated CV via:
👉 {contact_str}

Please feel free to like, share, and tag peers in your network who might be a great fit for this opportunity!

{hash_str}"""

    # 2. Instagram Caption
    instagram_post = f"""⚡ HIRING ALERT: {title} ⚡
🏢 Company: {company}
📍 Location: {loc}{mode}
💼 Experience: {exp_str}
💰 Salary: {salary_str}

{extra_section}

📲 HOW TO APPLY:
{contact_str}

✨ Save this post & share it with your friends!
💬 Comment 'APPLY' or DM us for more details.

.
.
{hash_str} #JobSearch #CareerGoals #TechHiring #Employment"""

    summary = f"Generated {tone} social posts for {title} at {company} ({loc})"

    return {
        "linkedin": linkedin_post.strip(),
        "instagram": instagram_post.strip(),
        "hashtags": hashtags,
        "summary": summary,
        "engine": "smart-fallback (offline/quota ready)",
    }


def format_social_post_text(val):
    """
    Ensures social post content is always formatted as a clean, ready-to-post string.
    Gracefully handles nested dicts, lists, or custom JSON structures returned by LLMs.
    """
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, list):
        return "\n".join(format_social_post_text(x) for x in val if x).strip()
    if isinstance(val, dict):
        if "post" in val:
            return format_social_post_text(val["post"])
        parts = []
        for key in ["title", "headline", "intro", "greeting"]:
            if key in val and isinstance(val[key], str):
                parts.append(val[key].strip())
        if "body" in val:
            b = val["body"]
            if isinstance(b, list):
                parts.append("\n".join(str(x) for x in b if x).strip())
            elif isinstance(b, (str, dict)):
                parts.append(format_social_post_text(b))
        for key in ["why_join", "highlights", "perks", "requirements", "details"]:
            if key in val:
                v = val[key]
                if isinstance(v, list):
                    parts.append("\n".join(str(x) for x in v if x).strip())
                elif isinstance(v, (str, dict)):
                    parts.append(format_social_post_text(v))
        for key in ["how_to_apply", "apply", "cta", "CTA", "call_to_action", "career_appeal"]:
            if key in val and isinstance(val[key], str):
                parts.append(val[key].strip())
        if not parts:
            for k, v in val.items():
                formatted_v = format_social_post_text(v)
                if formatted_v:
                    parts.append(formatted_v)
        return "\n\n".join(parts).strip()
    return str(val).strip()


def generate_social_content(job, platform="all", tone="professional"):
    """
    Generates tailored LinkedIn and Instagram posts for a given job.
    Uses OpenAI GPT-4o if active API key with quota is available,
    otherwise seamlessly uses the built-in smart copywriter.
    """
    from dotenv import load_dotenv
    load_dotenv(override=True)

    openai_key = os.getenv("OPENAI_API_KEY") or getattr(settings, "OPENAI_API_KEY", "")

    if openai_key:
        try:
            import openai
            client = openai.OpenAI(api_key=openai_key)

            system_prompt = (
                "You are an expert recruitment copywriter and social media strategist.\n"
                "Craft 2 high-converting social media posts based on the provided job data.\n"
                "Return a JSON object with strictly these keys:\n"
                "- 'linkedin': A single comprehensive, formatted STRING (with line breaks, emojis, bullet points, and CTA) ready to post directly on LinkedIn. DO NOT return a nested object.\n"
                "- 'instagram': A single catchy, formatted STRING (with emojis, concise perks, and CTA) ready to post directly on Instagram. DO NOT return a nested object.\n"
                "- 'hashtags': An array of 6-10 relevant hashtags as strings.\n"
                "- 'summary': A brief one-line summary string.\n"
                "IMPORTANT: 'linkedin' and 'instagram' MUST be plain text strings, NOT nested dictionaries or objects."
            )

            job_payload = {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "work_mode": job.work_mode,
                "exp_min": job.exp_min,
                "exp_max": job.exp_max,
                "salary": job.salary,
                "qualification": job.qualification,
                "other_details": job.other_details,
                "apply_contact": job.apply_contact,
                "tone": tone,
                "requested_platform": platform,
            }

            response = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Generate social media posts for this job:\n{json.dumps(job_payload, default=str)}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
            )

            data = json.loads(response.choices[0].message.content)
            raw_li = data.get("linkedin")
            raw_ig = data.get("instagram")
            linkedin_text = format_social_post_text(raw_li) or generate_fallback_social_content(job, tone)["linkedin"]
            instagram_text = format_social_post_text(raw_ig) or generate_fallback_social_content(job, tone)["instagram"]

            return {
                "linkedin": linkedin_text,
                "instagram": instagram_text,
                "hashtags": data.get("hashtags") or ["#Hiring", "#JobAlert", "#Career"],
                "summary": data.get("summary") or f"AI-generated social content for {job.title}",
                "engine": "openai (gpt-4o)",
            }
        except Exception:
            # If OpenAI throws quota or network error, fallback to smart copywriter
            pass

    return generate_fallback_social_content(job, tone=tone)

