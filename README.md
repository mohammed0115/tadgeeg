# FinAI — نظام التدقيق المالي الذكي
### AI-Powered Financial Auditing Platform for GCC

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-4.2_LTS-092E20?style=flat-square&logo=django&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=flat-square&logo=sqlite&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=flat-square&logo=redis&logoColor=white)
![OpenAI](https://img.shields.io/badge/GPT--4o-Vision-412991?style=flat-square&logo=openai&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)
![ZATCA](https://img.shields.io/badge/ZATCA-Compliant-00A651?style=flat-square)
![License](https://img.shields.io/badge/License-Proprietary-red?style=flat-square)

**Arabic · English · RTL UI · Dark Mode**

</div>

---

## What is FinAI?

FinAI automates financial document auditing for Saudi Arabia and GCC businesses. Upload invoices (PDF, images, or ZIP batches), and the system:

- **Extracts** all fields using Tesseract OCR + GPT-4o Vision
- **Validates** against **30 structured rules** (header integrity, VAT 15%, duplicates, anomalies, document quality)
- **Scores** each invoice 0–100 and assigns a risk level (Low / Medium / High / Critical)
- **Detects** duplicates using SHA-256 hashing + business logic
- **Generates** AI audit narratives in Arabic and English
- **Enforces** ZATCA QR Code compliance

---

## Screenshots

| Dashboard | Invoice Detail | Upload |
|-----------|---------------|--------|
| KPIs · Charts · Risk distribution | 30-rule breakdown · Audit trail · Approve/Reject | Drag-drop · Batch processing · Per-file results |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 4.2 + Django REST Framework |
| AI / OCR | OpenAI GPT-4o Vision + Tesseract 5 |
| Task Queue | Celery 5 + Redis 7 |
| Database | SQLite 3 (default) |
| Frontend | Django Templates + Tailwind CSS (CDN) + Alpine.js 3 |
| Charts | Chart.js 4 |
| Auth | JWT (simplejwt) + Session |
| Containers | Docker + Docker Compose |
| API Docs | drf-spectacular (Swagger UI + ReDoc) |

---

## Quick Start

### Prerequisites
- Docker Desktop ≥ 24
- Docker Compose ≥ 2.20
- OpenAI API key with **GPT-4o** access

### 1. Configure environment

```bash
cp .env.development.example .env
```

For Docker or production-style deployments, keep using `.env.example` as the base.

Edit `.env` and set at minimum:

```env
SECRET_KEY=your-50-char-secret-key
OPENAI_API_KEY=sk-proj-...
SQLITE_NAME=db_runtime.sqlite3
SITE_URL=http://localhost:8000
```

### 2. Start all services

```bash
docker-compose up -d
```

This starts: **Django web** · **SQLite** · **Redis** · **Celery worker** · **Celery beat**

### 3. Initialize database

```bash
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser
```

By default, the app uses the SQLite file `db_runtime.sqlite3`. Override it with `SQLITE_NAME` if needed.

### 4. Access

| URL | Description |
|-----|-------------|
| `http://localhost:8000` | Web UI (Arabic/English) |
| `http://localhost:8000/api/docs/` | Swagger UI |
| `http://localhost:8000/api/redoc/` | ReDoc |
| `http://localhost:8000/admin/` | Django Admin |

---

## Project Structure

```
finai_backend/
├── apps/
│   ├── authentication/     # Users, orgs, JWT, 7 roles
│   ├── invoices/           # Core module — models, 30-rule engine, API
│   ├── documents/          # Generic document store + OCR tasks
│   ├── transactions/       # Journal entries, bank transactions
│   ├── audit/              # Audit cases (CASE-YYYY-NNNN)
│   ├── compliance/         # ZATCA / VAT / IFRS / GAAP / SAMA rules
│   ├── analytics/          # Anomaly detection, Benford's Law
│   ├── reports/            # AI report generation (8 sections)
│   └── frontend/           # Django template views (Web UI)
├── core/
│   └── services/
│       ├── invoice_validator.py    # ← 30 validation rules
│       ├── invoice_ai_service.py   # GPT-4o extraction
│       ├── ai_service.py           # Analytics + report narratives
│       └── ocr_service.py          # Tesseract wrapper
├── templates/              # HTML templates (Tailwind + Alpine.js)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## The 30 Validation Rules

Every invoice is scored against 30 rules across 6 groups:

| Group | Code | Rules | Focus |
|-------|------|-------|-------|
| Invoice Header | `INV-001–008` | 8 | Number, date, vendor, VAT number, totals |
| Duplicate Detection | `DUP-001–005` | 5 | SHA-256 hash, same vendor/amount/date |
| VAT Validation | `VAT-001–005` | 5 | 15% rate, math correctness, ZATCA QR |
| Anomaly Detection | `ANO-001–006` | 6 | Statistical outliers, new vendors, volume spikes |
| Financial Controls | `CTL-001–006` | 6 | Cost centre, account code, budget, approval |
| Document Quality | `DOC-001–004` | 4 | OCR confidence, tampering, QR presence |

**Validation score** = weighted sum (critical rules worth 25 pts, high 15, medium 8, low 3).  
**Risk level**: ≥85 → Low · ≥70 → Medium · ≥50 → High · <50 → Critical

---

## API Reference

Base URL: `/api/v1/`  
Auth: `Authorization: Bearer <jwt_token>`

### Key Endpoints

```
# Auth
POST   /auth/token/                 → Obtain JWT tokens
POST   /auth/token/refresh/         → Refresh access token

# Invoices
POST   /invoices/upload/            → Upload files (PDF/image/ZIP) + auto-validate
GET    /invoices/                   → List with filters: status, risk_level, is_duplicate
GET    /invoices/{id}/              → Detail + 30-rule breakdown + audit trail
POST   /invoices/{id}/approve/      → Approve or reject  {action, reason}
POST   /invoices/{id}/revalidate/   → Re-run all 30 rules
GET    /invoices/reports/spend/     → Monthly spend trend + vendor analysis
GET    /invoices/reports/risk/      → High-risk invoice report
GET    /invoices/reports/duplicates/→ Duplicate report

# Reports
POST   /reports/generate/           → Generate AI report  {report_type, language}
GET    /reports/                    → List saved reports

# Analytics
POST   /analytics/detect-anomalies/ → AI anomaly scan
POST   /analytics/benford-analysis/ → Benford's Law analysis

# Audit & Compliance
GET    /audit/cases/                → List audit cases
GET    /compliance/violations/      → List compliance violations
```

Full Swagger docs at `/api/docs/`

---

## Web Pages

| Page | URL | Features |
|------|-----|---------|
| Login | `/login/` | JWT auth · dark animated background |
| Dashboard | `/dashboard/` | 5 KPIs · spend chart · risk donut · flagged list · vendor bars · 30-rule ring chart |
| Upload | `/invoices/upload/` | Drag-drop · multi-file · ZIP · per-file rule results |
| Invoice List | `/invoices/` | 6 filters · search · pagination · quick approve |
| Invoice Detail | `/invoices/<id>/` | 30-rule breakdown with group tabs · audit trail · approve/reject modal |
| Batches | `/invoices/batches/` | Upload history with status |
| Reports | `/reports/` | 4 one-click AI report types · report viewer modal |
| Vendors | `/vendors/` | Risk-tiered table · spend bars · new vendor badges |
| Anomaly Detection | `/analytics/` | Benford chart · AI scan results · high-risk table |
| Audit Cases | `/audit/` | CASE-YYYY-NNNN case management |
| Compliance | `/compliance/` | ZATCA/VAT rule violations |
| Documents | `/documents/` | OCR-processed file registry |

---

## User Roles

| Role | Arabic | Key Access |
|------|--------|-----------|
| `SUPER_ADMIN` | مدير النظام | Full system access |
| `ORG_ADMIN` | مدير المؤسسة | All org data + user management |
| `FINANCIAL_MANAGER` | المدير المالي | Approve invoices + reports |
| `AUDITOR` | مدقق حسابات | Read all + create audit cases |
| `ZATCA_AUDITOR` | مدقق زاتكا | ZATCA compliance view |
| `ACCOUNTANT` | محاسب | Upload + edit own invoices |
| `VIEWER` | مشاهد | Read-only |

---

## Scheduled Jobs

| Job | Schedule | Description |
|-----|----------|-------------|
| `run_nightly_anomaly_scan` | Daily 02:00 AM | Scans all active invoices for anomalies |
| `generate_weekly_kpi_report` | Monday 06:00 AM | Generates Arabic executive summary |

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | ✅ | — | Django secret key (50 chars) |
| `OPENAI_API_KEY` | ✅ | — | GPT-4o API key |
| `SITE_URL` | ✅ | `http://localhost:8000` | Base URL used in emails and links |
| `POSTGRES_DB` | No | `finai_db` | Database name |
| `POSTGRES_USER` | No | `finai_user` | Database user |
| `REDIS_URL` | No | `redis://redis:6379/0` | Redis connection |
| `DEBUG` | No | `False` | Enable debug mode |
| `ALLOWED_HOSTS` | No | `localhost` | Comma-separated hosts |
| `MAX_UPLOAD_SIZE_MB` | No | `50` | Max invoice file size |

---

## Sample Data

Eight Excel files with 5,000 records each and embedded audit anomalies are included for testing:

| File | Anomalies |
|------|-----------|
| `01_Bank_Statements.xlsx` | ~3% unusually large transactions |
| `02_Purchase_Orders.xlsx` | ~4% suspicious prices + VAT errors |
| `03_Journal_Entries.xlsx` | 15% manual entries · ~2% imbalanced |
| `04_Payroll.xlsx` | Duplicate employee IDs (ghost employees) |
| `05_Expense_Reports.xlsx` | 12% missing receipts · duplicate claims |
| `06_VAT_Returns.xlsx` | ~5% declared vs paid discrepancies |
| `07_Fixed_Assets.xlsx` | Negative book values · wrong depreciation |
| `08_Sales_Receipts.xlsx` | Duplicate receipts · missing QR codes |

---

## Roadmap

- [ ] WebSocket real-time alerts (Django Channels)
- [ ] ZATCA Fatoora Phase 2 API integration
- [ ] Rate limiting per organisation
- [ ] Email notifications (SendGrid / SES)
- [ ] Unit test suite (pytest + factory-boy)
- [ ] React Native mobile app
- [ ] Custom rule builder UI
- [ ] Non-invoice document auditing (payroll, bank statements)

---

## License

Proprietary — Internal Use Only. See `LICENSE` for terms.

---

<div align="center">
Built with ❤️ for GCC Financial Compliance · ZATCA Compliant · Arabic First
</div>
