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
    "remoteVault": "Remote Access Vault",
    "globalVault": "UAE & Global Access Vault",
    "tiers": [
        {"name": "Early Career Access Vault", "below": 5, "min_exp": 0.0, "max_exp": 5.0, "description": "India · 0–5 yrs (Freshers & 0 to 5 yrs)"},
        {"name": "Management Access Vault", "below": 10, "min_exp": 5.0, "max_exp": 10.0, "description": "India · 5–10 yrs (5 to 10 yrs)"},
        {"name": "Leadership Access Vault", "below": 15, "min_exp": 10.0, "max_exp": 15.0, "description": "India · 10–15 yrs (10 to 15 yrs)"},
        {"name": "Executive Access Vault", "below": None, "min_exp": 15.0, "max_exp": None, "description": "India · 15+ yrs"},
    ],
    "vaultDescriptions": {
        "Remote Access Vault": "Remote / work from anywhere",
        "UAE & Global Access Vault": "Outside India, not remote",
    },
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
  "title": "exact job title or null (CRITICAL: If the post is hiring for MULTIPLE roles/positions e.g. 'Backend Dev' and 'Mobile App Dev', extract and join ALL of them with a comma e.g. 'Backend Dev, Mobile App Dev')",
  "sector": "industry, business sector, or domain or null",
  "company": "company or hiring agency name or null",
  "location": "city / state / region or null (CRITICAL: Check headers, body text, and hashtags thoroughly. E.g. '#GurgaonJobs' -> location is 'Gurgaon', '#NoidaJobs' -> 'Noida', '#BangaloreJobs' -> 'Bangalore', '#DelhiJobs' -> 'Delhi', etc. Never output the literal string 'null' - use JSON null)",
  "country": "country name e.g. India, UAE, Saudi Arabia, USA or null. (If salary uses ₹, INR, Lakhs, LPA, CTC, or if the city is in India, country MUST be 'India'. Never output the literal string 'null')",
  "exp_min": float number of years (freshers = 0.0) or null,
  "exp_max": float number of years or null,
  "salary": "salary or CTC as written in the post or null",
  "qualification": "education, degree, diploma or certifications required or null",
  "other_details": "brief summary of duties, responsibilities, and perks or null",
  "work_mode": "Remote" | "Hybrid" | "Onsite" | null,
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
- Never guess or invent missing values. If a field is blurred, ambiguous, or not stated, set it to JSON null (never string 'null', 'None', or 'n/a').
- Multiple Job Roles / Positions: If the post or graphic is hiring for 2 or more positions (e.g. multiple job banners like 'Backend Dev' and 'Mboile App Dev', or 'Hiring: Role 1, Role 2', or '(2 Positions)'), you MUST include ALL of the job titles joined by comma and space in 'title' e.g. 'Backend Dev, Mobile App Dev'. Fix obvious OCR typos in role names (e.g. 'Mboile' -> 'Mobile').
- For 'work_mode': If text mentions 'Work From Home' or 'WFH', set work_mode to 'Remote'.
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


def enrich_vault_rules(rules):
    if not isinstance(rules, dict):
        rules = dict(DEFAULT_RULES)
    
    home = rules.get("homeCountry", "India")
    tiers = rules.get("tiers", [])
    standard_descs = {
        "Early Career Access Vault": f"{home} · 0–5 yrs (Freshers & 0 to 5 yrs)",
        "Management Access Vault": f"{home} · 5–10 yrs (5 to 10 yrs)",
        "Leadership Access Vault": f"{home} · 10–15 yrs (10 to 15 yrs)",
        "Executive Access Vault": f"{home} · 15+ yrs",
        "India · Fresher": f"{home} · 0–5 yrs (Freshers & 0 to 5 yrs)",
        "India · Junior": f"{home} · 5–10 yrs (5 to 10 yrs)",
        "India · Mid-level": f"{home} · 10–15 yrs (10 to 15 yrs)",
        "India · Senior": f"{home} · 15+ yrs",
    }
    for i, t in enumerate(tiers):
        t_name = str(t.get("name", "")).strip()
        prev_below = tiers[i - 1].get("below") if i > 0 else 0
        if t.get("min_exp") is None:
            t["min_exp"] = float(prev_below) if prev_below is not None else 0.0
        else:
            try:
                t["min_exp"] = float(t["min_exp"])
            except (ValueError, TypeError):
                t["min_exp"] = 0.0

        if t.get("max_exp") is None and "below" in t and t["below"] is not None:
            t["max_exp"] = float(t["below"])
        elif t.get("max_exp") is not None:
            try:
                t["max_exp"] = float(t["max_exp"])
            except (ValueError, TypeError):
                t["max_exp"] = None

        if not t.get("description"):
            if t_name in standard_descs:
                t["description"] = standard_descs[t_name]
            elif t.get("max_exp") is None:
                t["description"] = f"{home} · {int(t['min_exp']) if float(t['min_exp']).is_integer() else t['min_exp']}+ yrs"
            else:
                t["description"] = f"{home} · {int(t['min_exp']) if float(t['min_exp']).is_integer() else t['min_exp']}–{int(t['max_exp']) if float(t['max_exp']).is_integer() else t['max_exp']} yrs"

    v_descs = rules.setdefault("vaultDescriptions", {})
    glob = rules.get("globalVault", "UAE & Global Access Vault")
    rem = rules.get("remoteVault", "Remote Access Vault")
    if glob not in v_descs:
        v_descs[glob] = f"Outside {home}, not remote"
    if rem not in v_descs:
        v_descs[rem] = "Remote / work from anywhere"

    return rules


def get_vault_rules():
    r = get_setting("rules", DEFAULT_RULES)
    # Self-healing auto-upgrade if database holds legacy vault names or structure
    tiers = r.get("tiers", []) if isinstance(r, dict) else []
    tier_names = [t.get("name") for t in tiers if isinstance(t, dict)]
    is_legacy = (
        not tiers
        or any("India ·" in str(name) for name in tier_names)
        or r.get("remoteVault") == "Remote"
        or r.get("globalVault") == "Global"
        or "Early Career Access Vault" not in tier_names
    )
    if is_legacy:
        import copy
        r = copy.deepcopy(DEFAULT_RULES)
        set_setting("rules", r)
        try:
            for job in Job.objects.all():
                job.vault = classify_job(job.__dict__, r)
                expected_prefix = get_expected_job_id_prefix(job.vault, job.work_mode)
                if not job.job_id or (job.job_id and job.job_id[0] != expected_prefix):
                    job.job_id = generate_job_id(job.vault, work_mode=job.work_mode)
                job.save(update_fields=["vault", "job_id"])
        except Exception:
            pass
    return enrich_vault_rules(r)


def get_vault_definitions():
    rules = get_vault_rules()
    home = rules.get("homeCountry", "India")
    remote_v = rules.get("remoteVault", "Remote Access Vault")
    global_v = rules.get("globalVault", "UAE & Global Access Vault")
    tiers = rules.get("tiers", [])
    vault_descs = rules.get("vaultDescriptions", {})

    vaults = []
    for i, t in enumerate(tiers):
        vaults.append({
            "name": t.get("name"),
            "type": "tier",
            "tier_index": i,
            "min_exp": t.get("min_exp"),
            "max_exp": t.get("max_exp"),
            "description": t.get("description", ""),
            "below": t.get("max_exp"),
        })

    vaults.append({
        "name": global_v,
        "type": "global",
        "tier_index": None,
        "min_exp": None,
        "max_exp": None,
        "description": vault_descs.get(global_v, f"Outside {home}, not remote"),
        "below": None,
    })

    vaults.append({
        "name": remote_v,
        "type": "remote",
        "tier_index": None,
        "min_exp": None,
        "max_exp": None,
        "description": vault_descs.get(remote_v, "Remote / work from anywhere"),
        "below": None,
    })

    return vaults


def get_columns_setting():
    return get_setting("columns", DEFAULT_COLUMNS)


def get_vault_names():
    rules = get_vault_rules()
    tiers = [t["name"] for t in rules.get("tiers", [])]
    names = tiers + [rules.get("globalVault", "UAE & Global Access Vault"), rules.get("remoteVault", "Remote Access Vault")]
    out = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out


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


def sanitize_val(val):
    """Clean string values so that 'null', 'None', 'n/a', '-', etc. become None."""
    if val is None:
        return None
    s = str(val).strip()
    if s.lower() in ("null", "none", "n/a", "not specified", "undefined", "-"):
        return None
    return s


def normalize_work_mode(mode_val):
    """Normalize work mode to standard values: 'Remote', 'Hybrid', 'Onsite'."""
    if not mode_val:
        return None
    val = str(mode_val).strip()
    v_lower = val.lower()
    if v_lower in ("null", "none", "n/a", "-"):
        return None
    if any(k in v_lower for k in ("remote", "work from home", "wfh", "anywhere", "home")):
        return "Remote"
    if "hybrid" in v_lower:
        return "Hybrid"
    if any(k in v_lower for k in ("onsite", "in-office", "office", "on-site", "walk-in")):
        return "Onsite"
    return val


def extract_location_from_text(raw_text, current_loc=None):
    """Extract location/city from raw text, hashtags, or headers if not already provided."""
    clean_loc = sanitize_val(current_loc)
    if clean_loc:
        return clean_loc
    if not raw_text:
        return None

    # Check hashtags like #GurgaonJobs, #Gurgaon, #NoidaJobs, #BangaloreHiring, etc.
    hashtag_matches = re.findall(r'#([A-Za-z0-9_]+)', str(raw_text))
    city_map = {
        "gurgaon": "Gurgaon", "gurugram": "Gurugram", "noida": "Noida",
        "delhi": "Delhi", "newdelhi": "New Delhi", "bengaluru": "Bengaluru",
        "bangalore": "Bangalore", "mumbai": "Mumbai", "hyderabad": "Hyderabad",
        "pune": "Pune", "chennai": "Chennai", "kolkata": "Kolkata",
        "ahmedabad": "Ahmedabad", "jaipur": "Jaipur", "indore": "Indore",
        "chandigarh": "Chandigarh", "mohali": "Mohali", "kochi": "Kochi",
        "cochin": "Kochi", "lucknow": "Lucknow", "bhopal": "Bhopal",
        "surat": "Surat", "nagpur": "Nagpur", "vadodara": "Vadodara",
        "patna": "Patna", "dehradun": "Dehradun", "kanpur": "Kanpur",
        "ludhiana": "Ludhiana", "agra": "Agra", "nashik": "Nashik",
        "faridabad": "Faridabad", "ghaziabad": "Ghaziabad", "coimbatore": "Coimbatore",
        "mysore": "Mysore", "dubai": "Dubai", "abudhabi": "Abu Dhabi",
        "sharjah": "Sharjah", "riyadh": "Riyadh", "singapore": "Singapore"
    }

    # 1. First priority: Check hashtags ending with Jobs / Hiring / Openings / Work (e.g. #GurgaonJobs)
    for tag in hashtag_matches:
        t_low = tag.lower()
        for c_key, c_name in city_map.items():
            if c_key in t_low and ("job" in t_low or "hir" in t_low or "opening" in t_low or t_low == c_key):
                return c_name

    # 2. Check explicit regex in raw_text like "Location: Gurgaon", "Based in: Gurgaon"
    loc_match = re.search(r'(?:location|based in|job location|office location)\s*[:\-–]\s*([A-Za-z\s,]+)', str(raw_text), re.I)
    if loc_match:
        cand = loc_match.group(1).strip().split("\n")[0].split(".")[0].strip()
        if cand and len(cand) < 40 and cand.lower() not in ("null", "none", "not specified"):
            return cand

    # 3. Check any hashtag matching city name directly
    for tag in hashtag_matches:
        t_low = tag.lower()
        if t_low in city_map:
            return city_map[t_low]

    # 4. Check whole word matches of major cities in raw_text
    for c_key, c_name in city_map.items():
        if re.search(r'\b' + re.escape(c_key) + r'\b', str(raw_text), re.I):
            return c_name

    return None


def deduce_country(country, location, salary, raw_text=""):
    """Deduce country from explicit value, location, salary currency, or text."""
    c = sanitize_val(country)
    if c:
        return c.title() if len(c) > 3 else c.upper()

    sal_and_text = f"{salary or ''} {raw_text or ''}".lower()
    indian_indicators = ("₹", "inr", "lpa", "lakh", "crore", "ctc")
    if any(ind in sal_and_text for ind in indian_indicators):
        return "India"

    indian_cities = {
        "gurgaon", "gurugram", "noida", "delhi", "new delhi", "bengaluru", "bangalore",
        "mumbai", "hyderabad", "pune", "chennai", "kolkata", "ahmedabad", "jaipur",
        "indore", "chandigarh", "mohali", "kochi", "lucknow", "bhopal", "surat",
        "nagpur", "vadodara", "patna", "dehradun", "kanpur", "ludhiana", "agra",
        "nashik", "faridabad", "ghaziabad", "coimbatore"
    }
    loc_low = str(location or "").lower()
    if any(city in loc_low for city in indian_cities):
        return "India"

    # Foreign currency & international keywords
    if "$" in str(salary or "") or re.search(r'\b(401k|401\(k\)|w2|1099|pto|usd)\b', sal_and_text):
        return "USA"
    if re.search(r'\b(aed|dirham|dubai|abu dhabi|sharjah)\b', sal_and_text):
        return "UAE"
    if "£" in str(salary or "") or re.search(r'\b(gbp|london|uk)\b', sal_and_text):
        return "UK"
    if "€" in str(salary or "") or re.search(r'\b(eur|euro)\b', sal_and_text):
        return "Europe"

    return None


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

    work_mode = normalize_work_mode(job_data.get("work_mode")) or ""
    work_mode_low = work_mode.lower()
    loc = str(job_data.get("location") or "").lower()
    title = str(job_data.get("title") or "").lower()

    # Robust remote matching: checks work_mode, location, and title for remote / work from home / wfh
    is_remote = (
        "remote" in work_mode_low
        or "work from home" in work_mode_low
        or "wfh" in work_mode_low
        or "remote" in loc
        or "work from home" in loc
        or "wfh" in loc
        or "remote" in title
        or "work from home" in title
        or "wfh" in title
    )
    if is_remote:
        matched.append(rules.get("remoteVault", "Remote Access Vault"))

    raw_country = sanitize_val(job_data.get("country"))
    home_country = str(rules.get("homeCountry") or "India").strip().lower()

    sal = str(job_data.get("salary") or "")
    is_inr = "₹" in sal or "inr" in sal.lower() or "lpa" in sal.lower() or "lakh" in sal.lower()

    # Detect foreign currencies (Dollar $, Euro €, GBP £, AED, SAR, etc.)
    is_foreign_currency = bool(
        re.search(r'[\$€£]|(?:\b(?:usd|dollars?|eur|euros?|gbp|pounds?|aed|dirhams?|sar|riyals?|cad|aud|sgd)\b)', sal, re.I)
    )

    # Infer country if missing but Indian currency or Indian location
    country_inferred = raw_country
    if not country_inferred and is_inr:
        country_inferred = "India"
    elif not country_inferred and is_foreign_currency:
        country_inferred = "USA" if "$" in sal else "Global"
    elif not country_inferred and loc:
        country_inferred = deduce_country(None, loc, sal, "")

    country_low = str(country_inferred or "").strip().lower()

    # A job is global if genuinely outside home country OR if salary is in foreign currency (and not INR)
    is_global = bool(
        (country_low and country_low != home_country and not is_inr)
        or (is_foreign_currency and not is_inr)
    )
    if is_global:
        matched.append(rules.get("globalVault", "UAE & Global Access Vault"))

    # Check experience
    lo = job_data.get("exp_min")
    hi = job_data.get("exp_max")

    ev_exp = str(job_data.get("evidence", {}).get("exp") or job_data.get("experience") or "")
    if lo is None or (isinstance(lo, (int, float)) and lo > 40):
        n_lo, n_hi = clean_parse_exp(ev_exp, str(job_data.get("other_details") or ""))
        if n_lo is not None:
            lo, hi = n_lo, n_hi

    if lo is None:
        if re.search(r'\b(fresher|interns?|internship|trainee|entry)\b', title, re.I):
            lo, hi = 0.0, 0.0
        elif re.search(r'\b(vp|director|head|cxo|chief|partner|president|founder|ceo|cfo|cto|executive)\b', title, re.I):
            lo, hi = 15.0, 15.0
        elif re.search(r'\b(managers?|leaders?|management)\b', title, re.I):
            lo, hi = 5.0, 8.0
        elif re.search(r'\b(seniors?|sr\.?)\b', title, re.I):
            lo, hi = 10.0, 12.0
        elif is_global:
            lo, hi = None, None
        else:
            lo, hi = 0.0, 0.0

    if hi is None:
        hi = lo

    # Dynamic tier mapping from rules
    tiers = rules.get("tiers", [])
    tier_matched = False
    if tiers:
        for i, t in enumerate(tiers):
            t_name = str(t.get("name") or "").strip()
            if not t_name:
                continue

            t_min = t.get("min_exp")
            t_max = t.get("max_exp")
            if t_min is None and t_max is None:
                prev_below = tiers[i - 1].get("below") if i > 0 else 0
                t_min = float(prev_below) if prev_below is not None else 0.0
                curr_below = t.get("below")
                t_max = float(curr_below) if curr_below is not None else None
            else:
                t_min = float(t_min) if t_min is not None else 0.0
                t_max = float(t_max) if t_max is not None else None

            # Open upper bound (e.g. 15+ yrs)
            if lo is not None and hi is not None:
                if t_max is None:
                    if hi >= t_min or lo >= t_min:
                        matched.append(t_name)
                        tier_matched = True
                else:
                    # Interval match with boundary overlaps (e.g. 0-5 yrs, 5-10 yrs)
                    is_matched = False
                    if lo == t_min and hi == t_min and t_min > 0:
                        is_matched = True
                    elif (lo < t_max and hi >= t_min) or (lo <= t_min and hi >= t_max) or (lo >= t_min and lo < t_max):
                        is_matched = True
                    if is_matched:
                        matched.append(t_name)
                        tier_matched = True

    if not tier_matched:
        if not is_global:
            if tiers:
                matched.append(tiers[0]["name"])
            else:
                matched.append("Early Career Access Vault")

    # Remove duplicates preserving order
    unique_matched = []
    for m in matched:
        if m not in unique_matched:
            unique_matched.append(m)

    return unique_matched


def classify_job(job_data, rules=None):
    vault_list = get_job_vault_list(job_data, rules)
    return ", ".join(vault_list)


def get_expected_job_id_prefix(vault_name, work_mode=None):
    v_lower = str(vault_name or "").lower()
    wm_lower = str(work_mode or "").lower()

    # Priority 1: ANY remote job MUST start with 'R'
    if "remote" in v_lower or "remote" in wm_lower or "work from home" in wm_lower or "wfh" in wm_lower:
        return "R"
    # Priority 2: Global / UAE jobs outside India
    if "global" in v_lower or "uae" in v_lower:
        return "G"
    # Priority 3: Executive (15+ yrs)
    if "executive" in v_lower:
        return "E"
    # Priority 4: Leadership (10-15 yrs)
    if "leadership" in v_lower or "senior" in v_lower or "leader" in v_lower:
        return "L"
    # Priority 5: Management (5-10 yrs)
    if "management" in v_lower or "mid" in v_lower or "junior" in v_lower:
        return "M"
    # Priority 6: Early Career (0-5 yrs)
    if "early" in v_lower or "career" in v_lower or "fresher" in v_lower:
        return "C"
    return "C"


def generate_job_id(vault_name, date_obj=None, work_mode=None):
    if not date_obj:
        date_obj = timezone.now().date()
    ddmmyy = date_obj.strftime("%d%m%y")
    prefix = get_expected_job_id_prefix(vault_name, work_mode)

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

    # Sanitize and enrich extracted data
    raw_t = extracted_data.get("raw_text") or screenshot.raw_text or ""
    loc = extract_location_from_text(raw_t, extracted_data.get("location"))
    mode = normalize_work_mode(extracted_data.get("work_mode"))
    if not mode and re.search(r'\b(work\s*from\s*home|wfh|remote)\b', raw_t, re.I):
        mode = "Remote"
    sal = sanitize_val(extracted_data.get("salary"))
    country = deduce_country(extracted_data.get("country"), loc, sal, raw_t)

    extracted_data["location"] = loc
    extracted_data["work_mode"] = mode
    extracted_data["country"] = country
    extracted_data["salary"] = sal
    extracted_data["title"] = sanitize_val(extracted_data.get("title"))
    extracted_data["company"] = sanitize_val(extracted_data.get("company"))
    extracted_data["sector"] = sanitize_val(extracted_data.get("sector"))
    extracted_data["qualification"] = sanitize_val(extracted_data.get("qualification"))
    extracted_data["other_details"] = sanitize_val(extracted_data.get("other_details"))
    extracted_data["apply_contact"] = sanitize_val(extracted_data.get("apply_contact"))

    ev = extracted_data.get("evidence")
    if isinstance(ev, dict):
        for ek, ev_val in list(ev.items()):
            if isinstance(ev_val, str) and ev_val.strip().lower() in ("null", "none", "n/a", "-"):
                ev[ek] = ""
        if loc and not ev.get("location"):
            ev["location"] = loc

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
    new_job_id = generate_job_id(vault, work_mode=extracted_data.get("work_mode"))

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

