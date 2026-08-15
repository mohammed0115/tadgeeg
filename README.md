# FinAI — نظام التدقيق المالي الذكي
### AI-Powered Financial Auditing Platform for GCC

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-5.2_LTS-092E20?style=flat-square&logo=django&logoColor=white)
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
- **Validates** according to document-specific checks and the configured Rule Engine path (header integrity, VAT, duplicates, anomalies, and document quality)
- **Scores** each invoice 0–100 and assigns a risk level (Low / Medium / High / Critical)
- **Detects** duplicates using SHA-256 hashing + business logic
- **Generates** AI audit narratives in Arabic and English
- **Enforces** ZATCA QR Code compliance

---

## Screenshots

| Dashboard | Invoice Detail | Upload |
|-----------|---------------|--------|
| KPIs · Charts · Risk distribution | Rule results · Audit trail · Approve/Reject | Drag-drop · Batch processing · Per-file results |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 5.2 LTS + Django REST Framework |
| AI / OCR | OpenAI GPT-4o Vision + Tesseract 5 |
| Task Queue | Celery 5 + Redis 7 |
| Database | SQLite 3 افتراضياً للتطوير؛ MySQL 8 عند تهيئة `DB_BACKEND=mysql` للنشر |
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

This starts: **Django web** · **Redis** · **Celery worker** · **Celery beat**. SQLite is a local file by default, not a separate container service.

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
│   ├── invoices/           # Core module — models, upload processing, API
│   ├── documents/          # Generic document store + OCR tasks
│   ├── transactions/       # Journal entries, bank transactions
│   ├── audit/              # Audit cases (CASE-YYYY-NNNN)
│   ├── compliance/         # ZATCA / VAT / IFRS / GAAP / SAMA rules
│   ├── analytics/          # Anomaly detection, Benford's Law
│   ├── reports/            # AI report generation (8 sections)
│   └── frontend/           # Django template views (Web UI)
├── core/
│   └── services/
│       ├── invoice_validator.py    # document validation helpers
│       ├── invoice_ai_service.py   # GPT-4o extraction
│       ├── ai_service.py           # Analytics + report narratives
│       └── ocr_service.py          # Tesseract wrapper
├── templates/              # HTML templates (Tailwind + Alpine.js)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Validation rules and result labels

لا توجد في الشيفرة الحالية «30 قاعدة» موحدة لكل فاتورة. المسارات تختلف بحسب نوع المستند وبحسب تعريفات Rule Engine المهيأة؛ يعدّ مسح AST **124** معرف `rule_code` فريداً في `apps/rule_engine/rules/`، فيما يحتوي `core/services/doc_validators/doc_validators.py` على **101** نداء بناء قاعدة عبر أنواع مستندات متعددة. لذلك لا ينبغي قراءة الجدول التالي كعداد تشغيل موحد أو كضمان أن كل قاعدة تنفذ على كل رفع.

| Group | Code family | Count status | Focus |
|-------|-------------|--------------|-------|
| Invoice Header | `INV-*` | يعتمد على مسار المستند | Number, date, vendor, VAT number, totals |
| Duplicate Detection | `DUP-*` | يعتمد على مسار المستند | SHA-256 hash, same vendor/amount/date |
| VAT Validation | `VAT-*` | يعتمد على مسار المستند | 15% rate, math correctness, ZATCA QR |
| Anomaly Detection | `ANO-*` | يعتمد على مسار المستند | Statistical outliers, new vendors, volume spikes |
| Financial Controls | `CTL-001–006` | ستة رموز مميزة في المصدر | Cost centre, account code, budget, approval |
| Document Quality | `DOC-*` | يعتمد على مسار المستند | OCR confidence, tampering, QR presence |

لا يعلن README صيغة أوزان عامة: حساب `validation_score` مرتبط بالمسار المنفذ. في `doc_validators`، تصنيف مستوى الخطر هو: ≥85 منخفض، ≥70 متوسط، ≥50 مرتفع، وأقل من 50 حرج؛ ولا يعمم ذلك على محرك المخاطر أو قرار الاعتماد الآخر.

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
GET    /invoices/{id}/              → Detail + rule results + audit trail
POST   /invoices/{id}/approve/      → Approve or reject  {action, reason}
POST   /invoices/{id}/revalidate/   → Re-run the configured audit path
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
| Dashboard | `/dashboard/` | KPIs · spend chart · risk donut · flagged list · vendor bars · rule-result summary |
| Upload | `/invoices/upload/` | Drag-drop · multi-file · ZIP · per-file rule results |
| Invoice List | `/invoices/` | 6 filters · search · pagination · quick approve |
| Invoice Detail | `/invoices/<id>/` | Rule-result breakdown with group tabs · audit trail · approve/reject modal |
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
| `DB_BACKEND` | No | `sqlite` | `sqlite` للتطوير المحلي أو `mysql` للنشر |
| `DB_NAME` | عند MySQL | — | اسم قاعدة MySQL 8 |
| `DB_USER` | عند MySQL | — | مستخدم قاعدة MySQL 8 |
| `DB_PASSWORD` | عند MySQL | — | كلمة مرور قاعدة MySQL 8 |
| `DB_HOST` / `DB_PORT` | عند MySQL | `127.0.0.1` / `3306` | مضيف ومنفذ MySQL 8 |
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
- [x] Pytest suite: 4,035 tests collected in the measured `claude` baseline
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
