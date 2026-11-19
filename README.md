# JobVault AI — Screenshot to Excel Automated Processing System

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2-green.svg)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.18-red.svg)](https://www.django-rest-framework.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B-blue.svg)](https://www.postgresql.org/)
[![OpenAI](https://img.shields.io/badge/OpenAI%20Vision-GPT--4o-orange.svg)](https://openai.com/)
[![Tests](https://img.shields.io/badge/Tests-11%20Passed-brightgreen.svg)](#verification--testing)

**JobVault AI** is an enterprise-grade intelligent automation system that ingests job screenshots and PDF documents from messaging and social channels (WhatsApp, LinkedIn, Telegram, Instagram), extracts full OCR characters and structured job attributes using **OpenAI Vision API (GPT-4o / GPT-4o-mini)**, performs smart deduplication and confidence scoring, automatically assigns standard categorized **Job IDs**, dual-routes jobs across multiple relevant access vaults, and exports the data into client-standard **12-Column multi-tab Excel workbooks** and CSV sheets.

---

## Table of Contents
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Job ID Standard Format & Vault Rules](#job-id-standard-format--vault-rules)
- [Cross-Vault Dual-Routing Architecture](#cross-vault-dual-routing-architecture)
- [Client Master Excel Schema (12 Columns)](#client-master-excel-schema-12-columns)
- [Technology Stack](#technology-stack)
- [Directory Structure](#directory-structure)
- [Installation & Setup](#installation--setup)
- [Environment Configuration (.env)](#environment-configuration-env)
- [API Reference](#api-reference)
- [Verification & Testing](#verification--testing)
- [License & Authors](#license--authors)

---

## Key Features

1. **Dual Ingestion (Screenshots & Multi-Page PDFs)**:
   - Ingests standalone screenshot images (`.png`, `.jpg`, `.jpeg`, `.webp`, `.heic`, `.bmp`).
   - Ingests single-page and multi-page PDF documents (`.pdf`).
   - Automatically renders each PDF page into high-resolution PNG images at 2.0x scale (~144 DPI) using `pypdfium2`, generating distinct screenshot records (`<Name> (Page N).png`) for independent OCR parsing, visual verification, and job extraction.

2. **Multi-Part Screenshot Combination (`Combine into 1 single job`)**:
   - Checkbox-enabled batch upload that allows combining 1–4 screenshot parts of a single elongated/scrolled job posting into one consolidated job listing.
   - Stitches multi-part OCR transcriptions, aggregates field information, and generates a single clean database entry.

3. **High-Detail OpenAI Vision OCR**:
   - Transcribes all readable characters from screenshots word-for-word into `raw_text` using `detail: high` mode.
   - Extracts structured fields: Role, Sector, Company, Location, Country, Experience, Salary, Qualification, Other Details, and How to Apply.
   - Preserves exact character evidence strings linking extracted data back to the image.

4. **Automated 5-Stage Processing Pipeline**:
   - `received` ➔ `reading` ➔ `verifying` ➔ `sorting` ➔ `saved`.
   - Real-time progress indicators for every processed screenshot.

5. **Cross-Vault Dual-Routing Engine**:
   - Intelligent multi-vault classification where jobs are automatically assigned to multiple relevant vaults simultaneously.
   - E.g., a Remote listing with 1-2 years experience is routed to both **`Remote`** AND **`India · Fresher`** vaults, ensuring complete visibility across both work-mode and experience-based recruiter pipelines.

6. **Intelligent Deduplication**:
   - SHA-style text normalization and fingerprint hashing (`Title|Company|Contact`).
   - Configurable deduplication lookback window (default: 30 days).
   - Duplicate jobs are automatically flagged and linked to the existing record without polluting the master sheet.

7. **Review Queue & Interactive Drawer**:
   - Side-by-side modal view comparing the original screenshot with the extracted OCR text.
   - Real-time inline field editing.
   - Single-click **Approve & add to sheet** or **Reject** actions.

8. **Client-Standard Job ID Generation**:
   - Automatically prefixes IDs based on vault type (`C-`, `M-`, `L-`, `E-`, `R-`, `G-`).
   - Date-stamped with daily sequence numbers (e.g. `E-141026-49`, `C-141126-01`, `R-191126-01`).

9. **Standardized 12-Column Excel & CSV Export**:
   - Generates Excel workbook with **All Jobs** master tab plus **dedicated Access Vault tabs**.
   - Identical 12 columns across every sheet with Navy Dark Header (`#15202C`), auto-width columns, and auto-filters.
   - In-app **Copy for Excel** feature copies the exact 12 columns formatted with tab delimiters for direct clipboard pasting.

10. **AI Social Media Content Generator (LinkedIn & Instagram)**:
    - Automatically generates high-converting, platform-optimized social media posts from screenshot OCR and job attributes.
    - **LinkedIn**: Professional format with engaging hook, company overview, role bullets, application link, and industry hashtags.
    - **Instagram**: Catchy caption with clean layout, emojis, quick-read summary, CTA, and 8-12 trending career hashtags.
    - 1-click copy buttons directly from the Job Drawer modal.

11. **Dual Theme (White / Light Mode & Dark Mode)**:
    - High-contrast, clean Light Mode and Dark Mode designed with CSS custom properties.
    - Instant 1-click toggle button (`☀️` / `🌙`) in the sidebar header with `localStorage` persistence.

12. **Secure Error Handling & API Key Masking**:
    - Graceful detection of API errors (401 Invalid Key, 429 Quota Exhaustion).
    - Masks secret keys in error messages and presents clear troubleshooting links and error banners.

13. **Direct Dashboard Access & JWT Security Suite**:
    - Direct unauthenticated access for internal dashboard usage at `http://127.0.0.1:8000/dashboard/`.
    - Complete production-ready JWT authentication suite with user registration, login, profile management, and password reset with 6-digit OTP verification.

---

## System Architecture

```mermaid
flowchart TD
    A["Job Upload (PNG, JPG, WEBP, PDF)"] --> B{"Multi-Part Combine Check"}
    B -- "Combine Checkbox ON" --> C1["Merge 1-4 Image Parts into 1 Job"]
    B -- "Standard Batch Upload" --> C2{"File Type Check"}
    C2 -- "PDF File" --> D1["pypdfium2 (2.0x / ~144 DPI Render)"]
    D1 --> D2["Split Pages into Individual Screenshots"]
    C2 -- "Image File" --> D2
    C1 --> E["5-Stage Pipeline Initiation (received)"]
    D2 --> E
    E --> F["OpenAI Vision API (GPT-4o detail: high)"]
    F --> G["Full OCR Raw Text Transcription"]
    F --> H["Structured JSON Field Extraction"]
    G --> I["Deduplication Fingerprint Check"]
    H --> I
    I -- "Duplicate Found" --> J["Mark as Duplicate (Linked to Parent)"]
    I -- "Missing Fields / Low Confidence" --> K["Send to Needs Review Queue"]
    I -- "Validated" --> L["Direct to In Sheet"]
    K --> M["Admin Review Drawer: Edit & Approve"]
    M --> L
    L --> N["Auto-Generate Job ID (Prefix-DDMMYY-Seq)"]
    N --> O["Cross-Vault Dual-Routing Engine"]
    O --> P["PostgreSQL Database (Vault_AI)"]
    P --> Q["Download Excel (12-Column, Multi-Tab Workbook)"]
    P --> R["CSV Export & Clipboard Copy"]
```

---

## Job ID Standard Format & Vault Rules

Every job in the system is assigned a standardized Job ID matching the client's specification:

$$\text{Format: } \mathbf{[Prefix]\text{-}[DDMMYY]\text{-}[NN]}$$

| Prefix | Access Vault Category | Target Audience & Experience Tier | Example Job ID |
| :---: | :--- | :--- | :--- |
| **`C-`** | **Early Career Access Vault** | Freshers, Interns, 0–2 years exp | `C-191126-01` |
| **`M-`** | **Management Access Vault** | Junior & Mid-level Managers (2–10 yrs) | `M-191126-02` |
| **`L-`** | **Leadership Access Vault** | Senior Leaders, Heads, Team Leads (10+ yrs) | `L-191126-01` |
| **`E-`** | **Executive Access Vault** | C-Suite, VP, Director, CXO (15+ yrs) | `E-191126-49` |
| **`R-`** | **Remote Access Vault** | Remote, Work-From-Home, Anywhere | `R-191126-01` |
| **`G-`** | **UAE & Global Access Vault** | Outside India, Gulf, International | `G-191126-01` |

---

## Cross-Vault Dual-Routing Architecture

In recruitment workflows, candidates search both by **work style** (e.g. Remote) and by **seniority level** (e.g. 0-2 yrs Fresher, 2-5 yrs Junior). JobVault AI implements an automated **Dual-Routing Matrix**:

```
                         ┌──► Vault 1: "Remote" (Work Mode Filter)
[Remote Job Extracted] ──┤
                         └──► Vault 2: "India · Fresher" or "India · Junior" (Experience Filter)
```

- When a job is marked as `Remote`, it is routed to the `Remote` vault **AND** placed into the matching experience tier (`India · Fresher`, `India · Junior`, etc.).
- Both vault tags appear in the Job Sheet table and are appropriately mirrored across the corresponding tabs in the downloaded Excel workbook.

---

## Client Master Excel Schema (12 Columns)

When downloading the Excel workbook (`/api/export.xlsx`), **all sheets** strictly adhere to this exact 12-column layout:

| Col # | Column Name | Source Field | Description | Alignment |
| :---: | :--- | :--- | :--- | :---: |
| **A** | **`S. No.`** | Sequence Counter | 1, 2, 3... per sheet | Center |
| **B** | **`Job ID`** | `job.job_id` | e.g. `R-191126-01` | Center |
| **C** | **`Date`** | Extracted / `created_at` | e.g. `19-11-2026` | Center |
| **D** | **`Role`** | `job.title` | Designation / Job Title | Left |
| **E** | **`Sector`** | `job.sector` | Industry / Domain | Left |
| **F** | **`Company`** | `job.company` | Company or Agency Name | Left |
| **G** | **`Salary`** | `job.salary` | Salary / Package / CTC | Left |
| **H** | **`Location`** | `job.location` | City / State / Onsite Location | Left |
| **I** | **`Experience`** | `job.experience` | Years of Experience required | Left |
| **J** | **`Qualification`**| `job.qualification` | Required Degree / Diploma | Left |
| **K** | **`Other Details`** | `job.other_details` | Job duties & requirements | Left |
| **L** | **`How to apply`** | `job.apply_contact` | Email, Phone, or URL | Left |

### Workbook Tab Structure:
1. `All Jobs` (Master overview of all jobs)
2. `India · Fresher` / `Early Career Access Vault`
3. `India · Junior`
4. `India · Mid-level` / `Management Access Vault`
5. `India · Senior` / `Leadership & Executive Access Vault`
6. `Remote` / `Remote Access Vault`
7. `Global` / `UAE & Global Access Vault`

---

## Technology Stack

- **Backend**: Python 3.10+, Django 5.2, Django REST Framework 3.18
- **Authentication**: AllowAny for direct dashboard access, SimpleJWT available for token-based authentication
- **Database**: PostgreSQL (`Vault_AI`)
- **PDF & Document Processing**: `pypdfium2` (native high-resolution page rendering), `pypdf`
- **AI OCR & Vision**:
  - **OpenAI Vision API**: `gpt-4o-mini` / `gpt-4o` with `detail: high`
  - **Google Gemini API**: `gemini-2.5-flash` / `gemini-1.5-flash` (fallback)
- **Image Processing**: Pillow (PIL)
- **Excel Engine**: `openpyxl` with custom styling (Navy Dark Header `#15202C`, auto-filters, text wrapping)
- **Frontend**: Single-Page Application (HTML5, Vanilla JS, CSS Custom Properties with Dual Light/Dark Themes)

---

## Directory Structure

```text
vault_ai_project/
├── requirements.txt
├── README.md
└── vault_ai/
    ├── manage.py
    ├── .env                         # Database and AI API configurations
    ├── requirements.txt
    ├── media/                       # Uploaded screenshots storage
    │   └── screenshots/
    ├── vault_ai/                    # Django project core
    │   ├── __init__.py
    │   ├── settings.py
    │   ├── urls.py
    │   └── wsgi.py
    └── myapp/                       # Main application
        ├── migrations/
        ├── models.py                # Screenshot, Job, AppSetting, ActivityLog
        ├── views.py                 # REST API Views, Excel/CSV exporters
        ├── serializers.py           # Model serializers
        ├── utils.py                 # Vision AI, OCR, Job ID generator, Dedupe
        ├── urls.py                  # API routing (pure path syntax)
        ├── tests.py                 # Automated unit test suite (11 tests)
        └── templates/
            └── dashboard.html       # Web Dashboard SPA (Light & Dark Theme)
```

---

## Installation & Setup

### 1. Prerequisites
- **Python 3.10+**
- **PostgreSQL 14+** running on `localhost:5432` with a database named `Vault_AI`.

### 2. Clone and Setup Environment

```powershell
# Navigate to the project root
cd "C:\Users\Dell Pc\Desktop\vault_ai_project\vault_ai"

# Create virtual environment (if not already created)
python -m venv venv

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Install required dependencies
pip install -r requirements.txt
```

### 3. Configure Database & Environment
Edit [`vault_ai/.env`](file:///c:/Users/Dell%20Pc/Desktop/vault_ai_project/vault_ai/.env):

```env
DEBUG=True
SECRET_KEY=django-insecure-your-secret-key-here

# PostgreSQL Database
DB_NAME=Vault_AI
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432

# AI OCR & Vision API Keys
OPENAI_API_KEY=sk-proj-your-openai-api-key-here
OPENAI_MODEL=gpt-4o-mini
GEMINI_API_KEY=
```

### 4. Run Migrations

```powershell
python manage.py makemigrations
python manage.py migrate
```

### 5. Start the Development Server

```powershell
python manage.py runserver 127.0.0.1:8000
```

Open your browser at:
- **Dashboard UI**: [http://127.0.0.1:8000/dashboard/](http://127.0.0.1:8000/dashboard/)
- **Root URL**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

---

## Environment Configuration (.env)

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `DEBUG` | `True` | Django debug mode |
| `SECRET_KEY` | *(Django Secret)* | Cryptographic security signing |
| `DB_NAME` | `Vault_AI` | PostgreSQL database name |
| `DB_USER` | `postgres` | Database username |
| `DB_PASSWORD` | `rahul` | Database password |
| `DB_HOST` | `localhost` | Database host |
| `DB_PORT` | `5432` | Database port |
| `OPENAI_API_KEY` | *(Optional)* | Enables OpenAI GPT-4o Vision OCR character reading |
| `OPENAI_MODEL` | `gpt-4o-mini` | Specifies OpenAI model (`gpt-4o-mini` or `gpt-4o`) |
| `GEMINI_API_KEY` | *(Optional)* | Enables Google Gemini Vision OCR |

---

## API Reference

### 1. Screenshots APIs

#### `GET /api/screenshots`
Fetches the list of uploaded screenshots and current background queue counts.
- **Query Params**: `limit` (default: 60)
- **Response**:
```json
{
  "items": [
    {
      "id": 18,
      "filename": "screenshot_01.png",
      "original_name": "Job_Post.png",
      "size": 184500,
      "image": "http://127.0.0.1:8000/media/screenshots/screenshot_01.png",
      "origin": "upload",
      "source_app": "WhatsApp",
      "stage": "saved",
      "raw_text": "Customer Support Executive...",
      "job_count": 1,
      "created_at": "2026-11-19 11:44:05",
      "jobs": [
        {
          "id": 1142,
          "code": "C-191126-01",
          "status": "synced"
        }
      ]
    }
  ],
  "queue": {
    "queued": 0,
    "running": 0
  }
}
```

#### `POST /api/screenshots`
Uploads one or more screenshot images or PDF documents for instant Vision AI reading.
- **Query Params**: `combine=true` (combines uploaded parts into 1 single job).
- **Content-Type**: `multipart/form-data`
- **Body**: `files`: Image files (`.png`, `.jpg`, `.jpeg`, `.webp`, `.heic`, `.bmp`) or PDF files (`.pdf`)
- **Response**: `201 Created`
```json
{
  "ids": [19, 20, 21]
}
```

#### `POST /api/screenshots/<id>/retry`
Re-runs OCR and parsing on a failed or review screenshot.
- **Response**: `{"ok": true}`

#### `DELETE /api/screenshots/<id>`
Deletes a screenshot and removes its non-synced draft jobs.
- **Response**: `{"ok": true}`

---

### 2. Jobs APIs

#### `GET /api/jobs`
List all extracted jobs with support for search and vault filtering.
- **Query Params**:
  - `status`: `all` | `synced` | `review` | `duplicate` | `rejected`
  - `vault`: `all` | `India · Fresher` | `Remote` | `Global` | ...
  - `source`: `all` | `WhatsApp` | `LinkedIn` | `Telegram` | `Instagram`
  - `q`: Search keyword (matches title, company, location, salary, job_id)
- **Response**:
```json
{
  "items": [
    {
      "id": 1142,
      "code": "R-191126-01",
      "job_id": "R-191126-01",
      "title": "Junior Talent Acquisition Specialist",
      "sector": "Recruitment",
      "company": "LevelupForWomen",
      "location": "Gurgaon (Remote)",
      "experience": "1+ Years",
      "salary": "₹20,000-25,000 per month",
      "qualification": "Graduate",
      "other_details": "Immediate joining required...",
      "work_mode": "Remote",
      "apply_contact": "hr@levelup.com",
      "vault": "Remote, India · Fresher",
      "confidence": 0.95,
      "status": "synced"
    }
  ]
}
```

#### `GET /api/jobs/<id>`
Fetch complete details, image link, raw OCR transcription, and field evidence for a specific job.

#### `PUT /api/jobs/<id>`
Edit job fields (Title, Sector, Company, Location, Salary, Experience, Qualification, Other Details, Work Mode, Contact).

#### `POST /api/jobs/<id>/approve`
Approve a pending job from the Review Queue and promote it to `synced` (In Sheet).
- Automatically assigns a formatted `Job ID` if missing.
- **Response**: Returns updated Job object.

#### `POST /api/jobs/<id>/reject`
Marks a job as `rejected`.
- **Response**: Returns updated Job object.

#### `POST /api/jobs/<id>/generate-content` (also supports `GET`)
Generates AI-crafted social media posts for LinkedIn and Instagram directly from the job details and screenshot OCR text.
- **Response**: `200 OK`
```json
{
  "ok": true,
  "job_id": "R-191126-01",
  "title": "Junior Talent Acquisition Specialist",
  "company": "LevelupForWomen",
  "content": {
    "linkedin": "🌟 We are Hiring! | Junior Talent Acquisition Specialist at LevelupForWomen 🚀\n\nAre you ready to take your recruitment career to the next level?...\n\n📌 Key Details:\n• Role: Junior Talent Acquisition Specialist\n• Company: LevelupForWomen\n• Location: Gurgaon (Remote)\n• Experience: 1+ Years\n• Salary: ₹20,000-25,000 per month\n\n📩 Apply Now: hr@levelup.com\n\n#TalentAcquisition #Hiring #RemoteWork #Recruitment",
    "instagram": "💼✨ NEW JOB ALERT: Junior Talent Acquisition Specialist!\n\nLevelupForWomen is looking for talent! 🚀\n\n━━━━━━━━━━━━━━━━━━━━\n🏢 Company: LevelupForWomen\n💼 Role: Junior Talent Acquisition Specialist\n📍 Location: Gurgaon (Remote)\n⏳ Experience: 1+ Years\n━━━━━━━━━━━━━━━━━━━━\n\n📩 Apply: hr@levelup.com\n\n#HiringNow #RemoteJobs #JobOpening #Careers",
    "summary": "Junior Talent Acquisition Specialist at LevelupForWomen (Remote)",
    "hashtags": ["#TalentAcquisition", "#RemoteJobs", "#HiringNow", "#Recruitment"]
  }
}
```

---

### 3. Export APIs

#### `GET /api/export.xlsx`
Downloads the complete **Client-Standard 12-Column Excel Workbook** (`Website_Load_Export.xlsx`).
- Contains `All Jobs` tab + individual Access Vault tabs.
- Custom Navy Dark `#15202C` header styling with auto-width columns.

#### `GET /api/export.csv`
Downloads the filtered or complete dataset in standard 12-column CSV format (`Website_Load_Export.csv`).

---

### 4. Authentication & Security Suite

The system implements a production-ready Authentication & Security workflow using JWT (JSON Web Tokens) and Django standard cryptographic tokens:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/auth/login` | Authenticates user with username/email and password, returns JWT Access & Refresh tokens. |
| `POST` | `/api/auth/signup` / `/api/auth/register` | Registers new administrator account. |
| `POST` | `/api/auth/token/refresh` | Refreshes expired JWT Access Token. |
| `GET` / `PUT` | `/api/auth/me` | Retrieves or updates the currently logged-in user profile. |
| `POST` | `/api/auth/change-password` | Authenticated user changes password (requires `old_password` and `new_password`). |
| `POST` | `/api/auth/forgot-password` | Initiates password reset by email. Generates secure reset token & 6-digit OTP (15 min expiry). |
| `POST` | `/api/auth/verify-reset-token` | Verifies whether the supplied OTP or reset token is valid before setting a new password. |
| `POST` | `/api/auth/reset-password` | Confirms and updates the user's password using the validated token or OTP. |
| `POST` | `/api/auth/logout` | Logs out the user and invalidates/blacklists the refresh token. |

---

### 5. System & Integration APIs

- `GET /api/stats`: Real-time KPI counts (Total screenshots, In Sheet jobs, Review queue, Vault breakdown).
- `GET /api/activity`: Activity audit trail logs.
- `GET /api/integrations`: Active AI vision provider status (`openai`, `gemini`, `mock`).
- `PUT /api/settings/ai`: Update AI threshold, strict validation, and deduplication settings.
- `PUT /api/settings/rules`: Update vault tier sorting rules and experience cutoffs.

---

## Verification & Testing

To run the complete automated test suite:

```powershell
cd "C:\Users\Dell Pc\Desktop\vault_ai_project\vault_ai"
.\venv\Scripts\python.exe manage.py test myapp
```

Expected result:
```text
Creating test database for alias 'default'...
Found 11 test(s).
System check identified no issues (0 silenced).
...........
----------------------------------------------------------------------
Ran 11 tests in 24.144s

OK
Destroying test database for alias 'default'...
```

---

## License & Authors
- **Developed by**: Dr. Design / Engineering Team
- **Project**: JobVault AI Automation System
- **All rights reserved**.
