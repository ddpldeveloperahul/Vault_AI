# JobVault AI — Screenshot & PDF to Excel Automated Processing System

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2-green.svg)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.18-red.svg)](https://www.django-rest-framework.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B-blue.svg)](https://www.postgresql.org/)
[![OpenAI](https://img.shields.io/badge/OpenAI%20Vision-GPT--4o-orange.svg)](https://openai.com/)
[![WhiteNoise](https://img.shields.io/badge/Static-WhiteNoise%206.12-purple.svg)](https://whitenoise.readthedocs.io/)
[![Gunicorn](https://img.shields.io/badge/Server-Gunicorn%20WSGI-black.svg)](https://gunicorn.org/)
[![Tests](https://img.shields.io/badge/Tests-13%20Passed-brightgreen.svg)](#verification--testing)

**JobVault AI** is an enterprise-grade intelligent automation platform that ingests job screenshots and multi-page PDF documents from messaging and social channels (WhatsApp, LinkedIn, Telegram, Instagram), extracts full OCR characters and structured job attributes using **OpenAI Vision API (GPT-4o / GPT-4o-mini)** and **Google Gemini Vision**, performs smart deduplication and confidence scoring, automatically generates standard categorized **Job IDs**, dual-routes jobs across multiple access vaults, and exports the data into client-standard **12-Column multi-tab Excel workbooks** and CSV sheets.

---

## Table of Contents
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Standard Access Vaults & Experience Tiers](#standard-access-vaults--experience-tiers)
- [Job ID Standard Format & Prefix Priority](#job-id-standard-format--prefix-priority)
- [Cross-Vault Dual-Routing Architecture](#cross-vault-dual-routing-architecture)
- [Server-Side Pagination Architecture](#server-side-pagination-architecture)
- [Dynamic Vaults Management (Admin Customization)](#dynamic-vaults-management-admin-customization)
- [PDF Page Limit & Ingestion Guardrails](#pdf-page-limit--ingestion-guardrails)
- [Client Master Excel Schema (12 Columns)](#client-master-excel-schema-12-columns)
- [Technology Stack](#technology-stack)
- [Directory Structure](#directory-structure)
- [Installation & Local Setup](#installation--local-setup)
- [Environment Configuration (.env)](#environment-configuration-env)
- [Production Deployment Guide](#production-deployment-guide)
- [API Reference (Comprehensive)](#api-reference-comprehensive)
  - [1. Authentication & Security Suite](#1-authentication--security-suite)
  - [2. Screenshots Ingestion APIs](#2-screenshots-ingestion-apis)
  - [3. Jobs Management & Review APIs](#3-jobs-management--review-apis)
  - [4. Access Vaults Management APIs](#4-access-vaults-management-apis)
  - [5. Settings & Rules APIs](#5-settings--rules-apis)
  - [6. Export APIs (Excel & CSV)](#6-export-apis-excel--csv)
  - [7. System Health, Stats & Activity Logs APIs](#7-system-health-stats--activity-logs-apis)
  - [8. Standard Pagination Query & Response Format](#8-standard-pagination-query--response-format)
- [Verification & Testing](#verification--testing)
- [License & Authors](#license--authors)

---

## Key Features

1. **Dual Ingestion (Screenshots & Multi-Page PDFs)**:
   - Ingests standalone screenshot images (`.png`, `.jpg`, `.jpeg`, `.webp`, `.heic`, `.bmp`).
   - Ingests single-page and multi-page PDF documents (`.pdf`).
   - Automatically renders each PDF page into high-resolution PNG images at 2.0x scale (~144 DPI) using `pypdfium2`, generating distinct screenshot records (`<Name> (Page N).png`) for independent OCR parsing, visual verification, and job extraction.

2. **PDF Page Upload Guardrail (1–100 Pages Limit)**:
   - Protects server memory, AI token quotas, and async worker pipelines by enforcing a maximum of **100 pages per PDF**.
   - If a document exceeds 100 pages, upload processing is safely halted and a clear, readable error banner is returned immediately:
     ```
     "PDF contains X pages, which exceeds the maximum limit of 100 pages. Please upload a PDF with 1-100 pages."
     ```

3. **Multi-Part Screenshot Combination (`Combine into 1 single job`)**:
   - Checkbox-enabled batch upload that allows combining 1–4 screenshot parts of a single elongated/scrolled job posting into one consolidated job listing.
   - Stitches multi-part OCR transcriptions, aggregates field information, and generates a single clean database entry.

4. **Multi-Role Job Extraction**:
   - When a job graphic hires for multiple positions (e.g. `Backend Dev` and `Mobile App Dev`), the Vision AI extracts all titles joined by comma e.g. `Backend Dev, Mobile App Dev`.

5. **Dynamic Access Vaults Architecture (0-5, 5-10, 10-15, 15+, Remote, Global)**:
   - Exact client-standard vault naming synchronized between Web UI, Database Rules, and Excel sheets.
   - Dedicated `✏️ Edit` button on each vault card and `+ Add Vault` header button.

6. **High-Detail OpenAI Vision & Gemini OCR**:
   - Transcribes all readable characters from screenshots word-for-word into `raw_text` using `detail: high` mode.
   - Extracts structured fields: Role, Sector, Company, Location, Country, Experience, Salary, Qualification, Other Details, and How to Apply.
   - Preserves exact character evidence strings linking extracted data back to the image.

7. **Cross-Vault Dual-Routing Engine**:
   - Intelligent multi-vault classification where jobs are automatically assigned to multiple relevant vaults simultaneously.
   - E.g., a Remote listing with 1-2 years experience is routed to both **`Remote Access Vault`** AND **`Early Career Access Vault`**, ensuring complete visibility across both work-mode and experience-based recruiter pipelines.

8. **Top Priority for Remote Job IDs (`R-`)**:
   - Any job with `work_mode == "Remote"`, WFH, or belonging to `Remote Access Vault` is guaranteed a Job ID prefix of **`R-`** (e.g. `R-241126-01`), regardless of other secondary experience tiers.

9. **Intelligent Deduplication**:
   - SHA-style text normalization and fingerprint hashing (`Title|Company|Contact`).
   - Configurable deduplication lookback window (default: 30 days).
   - Duplicate jobs are automatically flagged and linked to the existing record without polluting the master sheet.

10. **Review Queue & Interactive Drawer with Unblocked Approval**:
    - Side-by-side modal view comparing the original screenshot with the extracted OCR text.
    - Real-time inline field editing with support for approving jobs with empty/null fields or custom edits.
    - Single-click **Approve & add to sheet**, **Reject**, or **Restore** actions.

11. **Standardized 12-Column Excel & CSV Export**:
    - Generates Excel workbook with **All Jobs** master tab plus **6 dedicated Access Vault tabs**.
    - Identical 12 columns across every sheet with Navy Dark Header (`#15202C`), auto-width columns, and auto-filters.
    - In-app **Copy for Excel** feature copies the exact 12 columns formatted with tab delimiters for direct clipboard pasting.

12. **AI Social Media Content Generator (LinkedIn & Instagram)**:
    - Automatically generates high-converting, platform-optimized social media posts from screenshot OCR and job attributes.
    - **LinkedIn**: Professional format with engaging hook, company overview, role bullets, application link, and industry hashtags.
    - **Instagram**: Catchy caption with clean layout, emojis, quick-read summary, CTA, and 8-12 trending career hashtags.

13. **Strict Credential-Based Authentication**:
    - JWT Access and Refresh tokens with hashed password verification.
    - Full Forgot Password, OTP email delivery, and reset confirmation flow.

14. **Production Deployment Ready**:
    - Cross-platform dependency specification in `requirements.txt` (`gunicorn` on Linux; Windows OCR dependencies isolated).
    - `WhiteNoise` static file handling integrated safely into Django middleware.
    - Flexible database adapter supporting `DATABASE_URL` (cloud providers), PostgreSQL, and SQLite fallback.
    - `Procfile` included for container and cloud deployments.

15. **Full Server-Side & UI Pagination Across Large Datasets**:
    - High-performance server-side slicing across all high-volume tables: **Job Sheet**, **Screenshots (Inbox)**, **Review Queue**, and **Activity Log**.
    - Enforced safe default of **50 records per page** (configurable to `25`, `50`, or `100`), preventing DOM overload and slow load times.
    - Uniform API pagination envelope containing `total`, `page`, `page_size`, `total_pages`, `has_next`, and `has_prev`.
    - Responsive frontend pagination controls with `Showing X–Y of Z`, interactive `« Previous` and `Next »` buttons, page index, and instant per-page limit dropdown.

---

## System Architecture

```mermaid
flowchart TD
    A["Job Upload (PNG, JPG, WEBP, PDF)"] --> B{"File Type Check"}
    B -- "PDF Upload" --> C{"Page Count Guard\n(<= 100 pages?)"}
    C -- "Pages > 100" --> D["Reject with Error: Max 100 Pages Limit"]
    C -- "Pages 1-100" --> E["pypdfium2 (~144 DPI Render)"]
    E --> F["Split into High-Res Page Screenshots"]
    B -- "Image Files" --> G{"Multi-Part Combine Check"}
    G -- "Combine ON" --> H["Merge 1-4 Images into 1 Job"]
    G -- "Combine OFF" --> F
    H --> I["5-Stage Pipeline Initiation (received)"]
    F --> I
    I --> J["Vision AI (OpenAI GPT-4o / Google Gemini)"]
    J --> K["Full OCR Raw Text Transcription"]
    J --> L["Structured JSON Field Extraction"]
    K --> M["Deduplication Fingerprint Check"]
    L --> M
    M -- "Duplicate Detected" --> N["Flag Duplicate (Linked to Original)"]
    M -- "Low Confidence / Incomplete" --> O["Send to Review Queue"]
    M -- "Validated" --> P["Direct to In Sheet"]
    O --> Q["Admin Review Drawer: Edit & Approve"]
    Q --> P
    P --> R["Auto-Generate Standard Job ID (R-, C-, M-, L-, E-, G-)"]
    R --> S["Cross-Vault Dual-Routing Engine"]
    S --> T["Database (PostgreSQL / SQLite)"]
    T --> U["Download 12-Column Multi-Tab Excel (.xlsx)"]
    T --> V["CSV Export & Direct Clipboard Copy"]
```

---

## Standard Access Vaults & Experience Tiers

The system uses standard access vaults synchronized across the UI cards, database rules, and Excel export tabs:

| Vault Name | Experience Criteria | Purpose / Subtitle | Job ID Prefix |
| :--- | :--- | :--- | :---: |
| **`Early Career Access Vault`** | **0–5 Years** (`0.0 to 5.0 yrs`) | Freshers & Early Career roles | **`C-`** (Career) |
| **`Management Access Vault`** | **5–10 Years** (`5.0 to 10.0 yrs`) | Mid-level, Team Leads & Managers | **`M-`** (Management) |
| **`Leadership Access Vault`** | **10–15 Years** (`10.0 to 15.0 yrs`) | Senior Managers & Department Leads | **`L-`** (Leadership) |
| **`Executive Access Vault`** | **15+ Years** (`15.0+ yrs`) | C-Suite, VP, Director, CXO & Executives | **`E-`** (Executive) |
| **`Remote Access Vault`** | **Remote / WFH** | Work from anywhere / Home | **`R-`** (Remote) |
| **`UAE & Global Access Vault`** | **Outside India / International** | Outside India (non-remote or foreign currency) | **`G-`** (Global) |

---

## Job ID Standard Format & Prefix Priority

Every job in the system is assigned a standardized, date-stamped Job ID:

$$\text{Format: } \mathbf{[Prefix]\text{-}[DDMMYY]\text{-}[NN]}$$

### Prefix Assignment Priority Rules:
1. **Remote Jobs (`R-`) [Top Priority]**:
   Any job where `work_mode == "Remote"`, text contains "Work from home" / "WFH", or `Remote Access Vault` is present **ALWAYS** starts with `R-` (e.g. `R-241126-01`, `R-241126-02`).
2. **Global / International (`G-`)**:
   Jobs located outside India with foreign currency (non-remote) start with `G-` (e.g. `G-241126-01`).
3. **Executive (`E-`)**:
   Jobs requiring 15+ years of experience or C-Suite roles (VP, Director, CXO, CEO) start with `E-` (e.g. `E-241126-01`).
4. **Leadership (`L-`)**:
   Jobs requiring 10–15 years of experience start with `L-` (e.g. `L-241126-01`).
5. **Management (`M-`)**:
   Jobs requiring 5–10 years of experience start with `M-` (e.g. `M-241126-01`).
6. **Early Career (`C-`)**:
   Jobs requiring 0–5 years of experience (Freshers, Junior) start with `C-` (e.g. `C-241126-01`).

---

## Cross-Vault Dual-Routing Architecture

In recruitment workflows, candidates search both by **work style** (e.g. Remote) and by **seniority level** (e.g. 0-5 yrs Early Career, 5-10 yrs Management). JobVault AI implements an automated **Dual-Routing Matrix**:

```
                         ┌──► Vault 1: "Remote Access Vault" (Work Mode Filter)
[Remote Job Extracted] ──┤
                         └──► Vault 2: "Early Career Access Vault" (Experience Filter)
```

- When a job is marked as `Remote`, it is routed to `Remote Access Vault` **AND** placed into the matching experience tier (`Early Career Access Vault`, `Management Access Vault`, etc.).
- When a job offers compensation in US Dollars (`$`) or foreign currency and is Remote, it automatically routes to **`Remote Access Vault`** AND **`UAE & Global Access Vault`**.
- All vault tags appear in the Job Sheet table and are mirrored across corresponding tabs in the downloaded Excel workbook.

---

## Server-Side Pagination Architecture

To ensure high performance when dealing with hundreds or thousands of jobs and screenshots, JobVault AI enforces **server-side query slicing** and pagination across all large listing views.

### Standard Pagination Query Parameters:

| Parameter | Type | Default | Options | Description |
| :--- | :---: | :---: | :---: | :--- |
| `page` | Integer | `1` | `>= 1` | The current page number to fetch. |
| `page_size` | Integer | `50` | `25`, `50`, `100` *(Max: 100)* | The number of records to return in a single page. Default is safely capped at 50 to prevent frontend lag. |

### Standard JSON Pagination Envelope:

Every paginated endpoint returns data enclosed within a standardized `pagination` metadata object:

```json
{
  "items": [ ... ],
  "pagination": {
    "total": 128,
    "page": 1,
    "page_size": 50,
    "total_pages": 3,
    "has_next": true,
    "has_prev": false
  }
}
```

### Paginated UI Views:
1. **Job Sheet (`/job/` & `/jobs/`)**:
   - Default: `50` jobs per page (selector options: `25`, `50`, `100`).
   - Slices database records in descending ID order (`-id`).
   - Includes real-time filter preservation across search (`q`), `vault`, `status`, and `source`.
2. **Screenshots Inbox (`/inbox/` & `/screenshots/`)**:
   - Default: `50` screenshots per page (selector options: `25`, `50`, `100`).
   - Returns real-time processing queue counters alongside paginated cards.
3. **Review Queue (`/review/` & `/reviews/`)**:
   - Default: `25` jobs per page (selector options: `10`, `25`, `50`).
4. **Activity Log (`/activity/`)**:
   - Default: `50` log entries per page (selector options: `25`, `50`, `100`).

---

## Client Master Excel Schema (12 Columns)

When downloading the Excel workbook (`/api/export.xlsx`), **all sheets** strictly adhere to this exact 12-column layout:

| Col # | Column Name | Source Field | Description | Alignment |
| :---: | :--- | :--- | :--- | :---: |
| **A** | **`S. No.`** | Sequence Counter | 1, 2, 3... per sheet | Center |
| **B** | **`Job ID`** | `job.job_id` | e.g. `R-241126-01`, `C-241126-01` | Center |
| **C** | **`Date`** | Extracted / `created_at` | e.g. `24-11-2026` | Center |
| **D** | **`Role`** | `job.title` | Designation / Job Title | Left |
| **E** | **`Sector`** | `job.sector` | Industry / Domain | Left |
| **F** | **`Company`** | `job.company` | Company or Agency Name | Left |
| **G** | **`Salary`** | `job.salary` | Salary / Package / CTC | Left |
| **H** | **`Location`** | `job.location` | City / State / Location | Left |
| **I** | **`Experience`** | `job.experience` | Years of Experience required | Left |
| **J** | **`Qualification`**| `job.qualification` | Required Degree / Diploma | Left |
| **K** | **`Other Details`** | `job.other_details` | Job duties & requirements | Left |
| **L** | **`How to apply`** | `job.apply_contact` | Email, Phone, or URL | Left |

### Workbook Tab Structure:
1. **`All Jobs`** (Master overview of all jobs)
2. **`Early Career Access Vault`** (0–5 yrs)
3. **`Executive Access Vault`** (15+ yrs)
4. **`Leadership Access Vault`** (10–15 yrs)
5. **`Management Access Vault`** (5–10 yrs)
6. **`Remote Access Vault`** (Remote / WFH)
7. **`UAE & Global Access Vault`** (International / UAE)

---

## Technology Stack

- **Backend Framework**: Python 3.10+, Django 5.2, Django REST Framework 3.18
- **WSGI Production Server**: Gunicorn 21.2+ (Linux/Cloud)
- **Static Asset Serving**: WhiteNoise 6.12+ (compressed, auto-manifest)
- **Database Engine**: PostgreSQL 14+ (production) / SQLite3 (development)
- **Authentication**: JWT (`rest_framework_simplejwt`) with strict password hashing
- **PDF & Rendering Engine**: `pypdfium2` (native ~144 DPI C-bindings rendering), `pypdf`
- **AI OCR & Vision Extraction**:
  - **OpenAI Vision API**: `gpt-4o-mini` / `gpt-4o` with `detail: high`
  - **Google Gemini API**: `gemini-2.5-flash` / `gemini-1.5-flash`
- **Image Processing**: Pillow (PIL) 12.3+
- **Excel & Spreadsheet Engine**: `openpyxl` 3.1+ (Navy Dark styling `#15202C`, auto-filters, text wrapping)
- **Frontend SPA**: Vanilla JavaScript, HTML5 History API, CSS Custom Properties (Dual Light & Dark Theme)

---

## Installation & Local Setup

### 1. Prerequisites
- **Python 3.10 or higher**
- **Git**
- **PostgreSQL 14+** (Optional: defaults automatically to SQLite if PostgreSQL is not active)

### 2. Clone and Setup Virtual Environment

```powershell
# Navigate to the project directory
cd "C:\Users\Dell Pc\Desktop\vault_ai_project\vault_ai"

# Create a virtual environment
python -m venv venv

# Activate virtual environment
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# Linux / macOS:
# source venv/bin/activate

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Create or verify `.env` inside `vault_ai/`:

```env
DEBUG=True
SECRET_KEY=django-insecure-your-secret-key-here
ALLOWED_HOSTS=*

# Database (Leave USE_POSTGRES=False to use SQLite out-of-the-box)
USE_POSTGRES=False
DB_NAME=Vault_AI
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432

# AI OCR & Vision API Keys
OPENAI_API_KEY=sk-proj-your-openai-api-key-here
OPENAI_MODEL=gpt-4o-mini
GEMINI_API_KEY=your-gemini-key-if-using
```

### 4. Run Migrations & Collect Static Files

```powershell
python manage.py makemigrations
python manage.py migrate
python manage.py collectstatic --noinput
```

### 5. Launch the Development Server

```powershell
python manage.py runserver 127.0.0.1:8000
```

Access the application in your browser:
- **Dashboard UI**: [http://127.0.0.1:8000/dashboard/](http://127.0.0.1:8000/dashboard/)
- **API Root**: [http://127.0.0.1:8000/api/](http://127.0.0.1:8000/api/)
- **Django Admin**: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

---

## API Reference (Comprehensive)

All API endpoints are prefixed with `/api/`. Requests and responses use standard `application/json` unless specified otherwise. Protected endpoints require `Authorization: Bearer <access_token>`.

### 1. Authentication & Security Suite

| Method | Endpoint | Auth Required | Description |
| :--- | :--- | :---: | :--- |
| `POST` | `/api/auth/login/` *(alias: `/api/login/`)* | No | Verifies credentials (username/email and password). Returns JWT `access` and `refresh` tokens and user profile. |
| `POST` | `/api/auth/signup/` *(alias: `/api/auth/register/`)* | No | Registers a new admin user. |
| `POST` | `/api/auth/token/refresh/` | No | Generates a new JWT access token using a valid `refresh` token. |
| `GET` | `/api/auth/me/` | **Yes** | Retrieves profile information for the authenticated user. |
| `PUT` | `/api/auth/me/` | **Yes** | Updates profile information (first name, last name, email) for the authenticated user. |
| `POST` | `/api/auth/change-password/` | **Yes** | Updates user password (requires `old_password`, `new_password`, `confirm_new_password`). |
| `POST` | `/api/auth/forgot-password/` | No | Initiates password reset for a given `email`. Generates `uidb64`, reset token, and a 6-digit OTP valid for 15 minutes. |
| `POST` | `/api/auth/verify-reset-token/` | No | Validates reset token (`uidb64` + `token`) or email + `otp` before allowing password reset. |
| `POST` | `/api/auth/reset-password/` | No | Resets password using validated `uidb64` + `token` (or email + `otp`) along with `new_password` and `confirm_new_password`. |
| `POST` | `/api/auth/logout/` *(alias: `/api/logout/`)* | No | Logs out user and blacklists the provided `refresh` token. |

#### Sample Login Request & Response:
```http
POST /api/auth/login/
Content-Type: application/json

{
  "username": "admin",
  "password": "admin123"
}
```
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "success": true,
  "message": "Login successful.",
  "user": {
    "id": 1,
    "username": "admin",
    "email": "admin@jobvault.ai",
    "role": "ADMIN"
  },
  "tokens": {
    "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }
}
```

---

### 2. Screenshots Ingestion APIs

| Method | Endpoint | Auth Required | Description |
| :--- | :--- | :---: | :--- |
| `GET` | `/api/screenshots/` | No | Lists uploaded screenshots with processing stages (`received`, `reading`, `verifying`, `sorting`, `saved`, `failed`). Supports server-side pagination with query parameters `?page=1&page_size=50` (options: `25`, `50`, `100`). Returns `items`, live `queue` status, and standard `pagination` envelope. |
| `POST` | `/api/screenshots/` | No | Ingests job screenshots (`.png`, `.jpg`, `.webp`) or PDF documents (`.pdf`). Supports query parameter `?combine=true` to merge up to 4 elongated screenshots into 1 single job. Enforces 1–100 pages limit on PDFs. |
| `GET` | `/api/screenshots/<id>/` | No | Retrieves details of a specific screenshot, raw OCR transcription, extracted jobs, and stage status. |
| `POST` | `/api/screenshots/<id>/retry/` | No | Re-runs OCR vision extraction on a failed or stuck screenshot. |
| `DELETE` | `/api/screenshots/<id>/` | No | Permanently deletes a screenshot and its associated pending jobs. |

#### Sample Paginated Screenshots Response:
```http
GET /api/screenshots/?page=1&page_size=50
```
```json
{
  "items": [
    {
      "id": 45,
      "filename": "screenshot_1732700000.png",
      "original_name": "job_post.png",
      "stage": "saved",
      "confidence": 94.5,
      "jobs": [
        { "id": 39, "code": "L-271126-01", "status": "synced" }
      ]
    }
  ],
  "queue": {
    "queued": 0,
    "running": 0
  },
  "pagination": {
    "total": 92,
    "page": 1,
    "page_size": 50,
    "total_pages": 2,
    "has_next": true,
    "has_prev": false
  }
}
```

#### Sample Screenshot Upload Request (`multipart/form-data`):
```http
POST /api/screenshots/?combine=false
Content-Type: multipart/form-data

files: [binary file data]
```

---

### 3. Jobs Management APIs

| Method | Endpoint | Auth Required | Description |
| :--- | :--- | :---: | :--- |
| `GET` | `/api/jobs/` | No | Lists all extracted jobs with server-side pagination. Enforces default `page_size=50` (options: `25`, `50`, `100`). Supports query filters: `?page=1&page_size=50`, `status` (`synced`, `review`, `duplicate`, `rejected`), `vault` (filter by vault name), `source` (`WhatsApp`, `LinkedIn`, `Telegram`, `Instagram`), and `q` (search title, company, location, Job ID). Returns `items` array and `pagination` metadata. |
| `GET` | `/api/jobs/<id>/` | No | Retrieves full details for a specific job, including extracted attributes, evidence substrings, and linked screenshot. |
| `PUT` | `/api/jobs/<id>/` | No | Updates job fields (`title`, `sector`, `company`, `location`, `country`, `salary`, `experience`, `qualification`, `other_details`, `work_mode`, `apply_contact`, `vault`). Automatically recalculates Job ID prefix if work mode/vault changes. |
| `POST` | `/api/jobs/<id>/approve/` | No | Promotes a review job to `synced` (In Sheet). Allows approving jobs with empty/null fields or after manual inline editing. Generates standard Job ID if not already assigned. |
| `POST` | `/api/jobs/<id>/reject/` | No | Moves a job to `rejected` status. |
| `POST` | `/api/jobs/<id>/restore/` | No | Restores a previously rejected job back to `review` status. |
| `DELETE` | `/api/jobs/<id>/` | No | Permanently deletes a job from the database. |
| `POST` | `/api/jobs/<id>/generate-content/` | No | Uses AI to generate platform-ready social media posts for **LinkedIn** and **Instagram**, complete with hashtags, summaries, and application CTAs. |

#### Sample Paginated Jobs Response:
```http
GET /api/jobs/?page=1&page_size=50&status=synced
```
```json
{
  "items": [
    {
      "id": 39,
      "job_id": "L-271126-01",
      "code": "L-271126-01",
      "title": "SAP FICO Consultant",
      "company": "Velodata",
      "location": "Remote",
      "vault": "Remote Access Vault, Management Access Vault, Leadership Access Vault",
      "status": "synced",
      "confidence": 99.0,
      "created_at": "2026-11-27T10:15:30Z"
    }
  ],
  "pagination": {
    "total": 128,
    "page": 1,
    "page_size": 50,
    "total_pages": 3,
    "has_next": true,
    "has_prev": false
  }
}
```

#### Sample Social Content Generation Response:
```json
{
  "ok": true,
  "job_id": "R-241126-01",
  "title": "Junior Talent Acquisition Specialist",
  "company": "LevelupForWomen",
  "content": {
    "linkedin": "🌟 We are Hiring! | Junior Talent Acquisition Specialist at LevelupForWomen 🚀\n\n📍 Location: Gurgaon (Work From Home)\n💼 Experience: 1+ Years\n💰 CTC: ₹20,000–25,000 per month\n\n👉 Apply Here: https://lnkd.in/gRCMmh9d\n\n#TalentAcquisition #RemoteJobs #Hiring #HRJobs",
    "instagram": "💼✨ NEW JOB ALERT: Junior Talent Acquisition Specialist!\n\n🏢 LevelupForWomen\n📍 Remote / Gurgaon\n⏳ 1+ Years Experience\n💵 ₹20k - ₹25k / mo\n\nApply via link in bio! 📲\n\n#Hiring #WorkFromHome #Recruiter #JobOpportunity",
    "summary": "Junior Talent Acquisition Specialist at LevelupForWomen (Remote)",
    "hashtags": ["#TalentAcquisition", "#RemoteJobs", "#HiringNow", "#Recruitment"]
  }
}
```

---

### 4. Access Vaults Management APIs

| Method | Endpoint | Auth Required | Description |
| :--- | :--- | :---: | :--- |
| `GET` | `/api/vaults/` | No | Returns all configured access vaults, their type (`tier`, `remote`, `global`), experience bounds (`min_exp`, `max_exp`), descriptions, and live synchronized job counts. |
| `POST` | `/api/vaults/` | No | Adds a new access vault. Automatically triggers re-classification of existing jobs in the database. |
| `PUT` | `/api/vaults/<vault_name>/` *(or `PUT /api/vaults/`)* | No | Modifies vault name, experience criteria (`min_exp`, `max_exp`), or description. Updates vault tags across all jobs matching the new criteria. |
| `DELETE` | `/api/vaults/<vault_name>/` | No | Deletes a custom access vault and redistributes jobs. System remote/global vaults are protected against accidental deletion. |

#### Sample `GET /api/vaults/` Response:
```json
{
  "success": true,
  "homeCountry": "India",
  "remoteVault": "Remote Access Vault",
  "globalVault": "UAE & Global Access Vault",
  "vaults": [
    {
      "name": "Early Career Access Vault",
      "type": "tier",
      "tier_index": 0,
      "min_exp": 0.0,
      "max_exp": 5.0,
      "description": "India · 0–5 yrs (Freshers & 0 to 5 yrs)",
      "below": 5.0,
      "count": 4
    },
    {
      "name": "Management Access Vault",
      "type": "tier",
      "tier_index": 1,
      "min_exp": 5.0,
      "max_exp": 10.0,
      "description": "India · 5–10 yrs (5 to 10 yrs)",
      "below": 10.0,
      "count": 2
    },
    {
      "name": "Leadership Access Vault",
      "type": "tier",
      "tier_index": 2,
      "min_exp": 10.0,
      "max_exp": 15.0,
      "description": "India · 10–15 yrs (10 to 15 yrs)",
      "below": 15.0,
      "count": 0
    },
    {
      "name": "Executive Access Vault",
      "type": "tier",
      "tier_index": 3,
      "min_exp": 15.0,
      "max_exp": null,
      "description": "India · 15+ yrs",
      "below": null,
      "count": 0
    },
    {
      "name": "UAE & Global Access Vault",
      "type": "global",
      "tier_index": null,
      "min_exp": null,
      "max_exp": null,
      "description": "Outside India, not remote",
      "below": null,
      "count": 2
    },
    {
      "name": "Remote Access Vault",
      "type": "remote",
      "tier_index": null,
      "min_exp": null,
      "max_exp": null,
      "description": "Remote / work from anywhere",
      "below": null,
      "count": 4
    }
  ]
}
```

---

### 5. Settings & Rules APIs

| Method | Endpoint | Auth Required | Description |
| :--- | :--- | :---: | :--- |
| `GET` | `/api/settings/` | No | Retrieves global application settings including AI vision configuration, vault rules, and active column definitions. |
| `GET` | `/api/settings/ai/` | No | Returns AI vision settings (`provider`, `threshold`, `strict`, `dedupe`, `dedupeDays`, `extraInstructions`). |
| `PUT` | `/api/settings/ai/` | No | Updates AI vision settings and deduplication parameters. |
| `GET` | `/api/settings/rules/` | No | Retrieves current vault classification rules and tier boundaries. |
| `PUT` | `/api/settings/rules/` | No | Updates vault classification rules and saves to database. |
| `POST` | `/api/rules/test/` | No | Simulates job classification for arbitrary input (`country`, `work_mode`, `exp_min`, `exp_max`, `salary`) without modifying database records. |
| `GET` | `/api/settings/columns/` | No | Retrieves client sheet column definitions, labels, and required flags. |
| `PUT` | `/api/settings/columns/` | No | Reorders, enables/disables, or updates column definitions. |

---

### 6. Export APIs (Excel & CSV)

| Method | Endpoint | Auth Required | Description |
| :--- | :--- | :---: | :--- |
| `GET` | `/api/export.xlsx` | No | Downloads the complete **12-Column Multi-Tab Excel Workbook** (`Website_Load_Export.xlsx`). Contains `All Jobs` tab plus tabs for each vault (`Early Career Access Vault`, `Management Access Vault`, `Leadership Access Vault`, `Executive Access Vault`, `Remote Access Vault`, `UAE & Global Access Vault`). |
| `GET` | `/api/export.csv` | No | Downloads job records formatted in the client standard 12-column layout as a CSV file (`Website_Load_Export.csv`). Supports filtering by `?vault=`, `?source=`, `?status=`, and `?q=`. |

---

### 7. System Health, Stats & Monitoring APIs

| Method | Endpoint | Auth Required | Description |
| :--- | :--- | :---: | :--- |
| `GET` | `/api/health/` | No | System health check endpoint. Returns `{"ok": true, "provider": "mock", "authRequired": false}`. |
| `GET` | `/api/stats/` | No | Provides real-time metrics for Dashboard KPI cards: total screenshots, synced in-sheet jobs, review queue count, duplicate counts, jobs by vault, jobs by source, and 14-day daily processing trend graph. |
| `GET` | `/api/activity/` | No | Retrieves system audit trail logs (`ADMIN_LOGIN`, `Review`, `VAULT_CREATED`, `ADMIN_PASSWORD_CHANGE`). Supports server-side pagination: `?page=1&page_size=50` (options: `25`, `50`, `100`). Returns `items` array and `pagination` envelope. |
| `GET` | `/api/integrations/` | No | Returns available AI Vision providers (`openai`, `gemini`, `mock`), configured models, and active connection status. |

#### Sample Paginated Activity Log Response:
```http
GET /api/activity/?page=1&page_size=50
```
```json
{
  "items": [
    {
      "id": 104,
      "action": "Admin",
      "details": "Vault rules updated · 2 jobs re-sorted",
      "created_at": "2026-11-27T10:04:12Z"
    }
  ],
  "pagination": {
    "total": 348,
    "page": 1,
    "page_size": 50,
    "total_pages": 7,
    "has_next": true,
    "has_prev": false
  }
}
```

---

## Verification & Testing

To execute the automated unit and integration test suite:

```powershell
cd "C:\Users\Dell Pc\Desktop\vault_ai_project\vault_ai"
.\venv\Scripts\python.exe manage.py test myapp
```

Output:
```text
Creating test database for alias 'default'...
Found 13 test(s).
System check identified no issues (0 silenced).
.............
----------------------------------------------------------------------
Ran 13 tests in 14.209s

OK
Destroying test database for alias 'default'...
```

---

## License & Authors
- **Developed by**: Dr. Design / Engineering Team
- **Project**: JobVault AI Automation System
- **All rights reserved**.
