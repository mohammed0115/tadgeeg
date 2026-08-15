Architecture Review: Tadgeeg AI Financial Audit Platform
A. Executive Summary
Overall Codebase Health: 5.5 / 10

The codebase has a genuinely solid domain model, a well-conceived three-stage pipeline, and good separation between apps. But three years of layered growth without a consistent architectural contract have produced dangerous structural debt. The core upload path is already at the limit of maintainability. Adding major new modules (ERP connectors, workflow engines, advanced risk models) without first resolving the structural issues below will produce increasingly fragile, untestable code.

Main Architectural Risks
The invoice processing pipeline runs three overlapping execution paths simultaneously — no single source of truth for what "auditing an invoice" means.
Business-critical processing logic lives inside views.py, making it unreachable by Celery tasks without circular imports.
Race conditions in AuditCase and CustomRuleDefinition save methods will cause data corruption under concurrent load.
Main Maintainability Risks
_process_single_file in views.py is a 250-line god function with 9 orchestration steps — every new requirement touches it.
Four apps named audit* with overlapping responsibility make it impossible to know which audit system is canonical.
Duplicate private helpers across views.py and validation_service.py create silent divergence over time.
Main Scalability Risks
InvoiceValidationResult has 30 boolean columns mirroring 30 rules — adding a rule requires a schema migration.
AuditCase.case_number is generated with a COUNT + 1 pattern that produces duplicates under concurrent inserts.
_process_structured_rows_chunk is imported by a Celery task from views.py — this creates a hidden coupling that prevents proper horizontal scaling.
B. Critical Problems
CP-1: Processing Pipeline Lives in views.py
File: apps/invoices/views.py

_process_single_file (line 237), _process_structured_upload (line 804), _process_structured_rows_chunk (line 737), _process_zip (line 1094), and all _iter_* parsers are module-level functions in a views file.

Why dangerous: apps/invoices/tasks.py line 64 imports _process_structured_rows_chunk directly from views.py:


from apps.invoices.views import _process_structured_rows_chunk
A Celery worker imports a view file every time a task runs. This loads the entire view module including DRF parsers, form parsers, serializer imports, and all authentication middleware dependencies. It also creates a latent circular import risk. When you add more logic to this function, Celery workers break.

CP-2: Three Competing Audit Execution Paths
Inside _process_single_file, three separate audit systems run on the same invoice:


# Path 1 — legacy engine (apps/audit/audit_engine.py)
run_audit(analysis.to_dict(), organization_id=..., invoice_id=..., persist=True)

# Path 2 — new rule engine (apps/rule_engine/pipeline/v2/pipeline.py, 97 rules)
run_audit_task.delay(document_id=str(invoice.id), ...)

# Path 3 — 30-rule ZATCA validator (core/services/invoice_validator.py)
val_result = ValidationPipelineService.validate_invoice(invoice=invoice, ...)
Why dangerous: Three systems can produce contradictory scores. The final risk_score is a max() of the V1 AI score and the rule-based fallback, but the V2 pipeline runs asynchronously and its results are never merged back. AuditFinding records come from multiple sources with overlapping rule_code values. There is no canonical answer to "what is the audit result for this invoice."

CP-3: Race Condition in AuditCase.save()
File: apps/audit/models.py


def save(self, *args, **kwargs):
    if not self.case_number:
        count = AuditCase.objects.filter(organization=self.organization).count()
        year = datetime.datetime.now().year
        self.case_number = f"CASE-{year}-{count + 1:04d}"
    super().save(*args, **kwargs)
Why dangerous: Two concurrent requests for the same organization both call COUNT() before either inserts, getting the same count, then both insert CASE-2026-0042. case_number has unique=True so one will raise an IntegrityError in production. This will start appearing once batch uploads scale.

CP-4: Race Condition in CustomRuleDefinition.save()
File: apps/audit/models.py


def save(self, *args, **kwargs):
    if self.pk:
        CustomRuleDefinition.objects.filter(pk=self.pk).update(version=models.F("version") + 1)
        self.version = CustomRuleDefinition.objects.get(pk=self.pk).version  # second query
    super().save(*args, **kwargs)
Why dangerous: The update() and the following get() are not in a transaction. The value read back in the get() may have been incremented by another request between the two queries. The save() that follows then writes the stale or wrong version back to all fields.

CP-5: CustomRuleDefinition.evaluate() is Business Logic on a Django Model
File: apps/audit/models.py

This method does database queries (InvoiceModel.objects.filter(...)) and imports other models inside a model's instance method. It cannot be tested without a database, makes serialization dangerous (trigger a .save() and business logic runs), and violates SRP.

C. Violations by Principle
Clean Code Violations
CC-1: _process_single_file does at least 9 distinct responsibilities

apps/invoices/views.py:237 — file upload, hash check, Invoice record creation, DocumentEngine ingestion, OpenAI extraction, field normalization, 20+ field assignments, FinancialAIEngine analysis, legacy audit engine, V2 rule engine dispatch, ZATCA validation, risk score merge, vendor profile update, canonical mapper save, audit event creation, AuditSession state machine advancement. The function is 250 lines.

CC-2: Nested function definitions inside a processing function

apps/invoices/views.py:348 — _safe_decimal and _safe_date are defined inside _process_single_file. They are pure utility functions with no closure over outer variables, yet they are redefined on every call.

CC-3: Magic numbers with no named constants

512 * 1024 (views.py:79) — async threshold
1.0 (models.py:223) — VAT math tolerance
0.5 (models.py:231) — VAT rate tolerance
78.0, 72.0, 58.0 (validation_service.py:83) — risk floor bumps
70, 40 (validation_service.py:57) — risk level thresholds
None of these are collected into a single constants module. The number 70 appears in at least 4 different files with different semantic meanings.

CC-4: Comment noise vs. intent

apps/invoices/models.py:111:


ai_summary = models.TextField(blank=True)  # AI智能摘要
A Chinese comment in an Arabic/English enterprise system — copy-paste artifact, never cleaned up.

CC-5: _first_non_empty is ambiguous

views.py:104 — the function returns "" for empty strings but 0 for falsy numerics and False for booleans. The contract is unclear from the name alone and the behavior differs by type.

SOLID Violations
S-1: SRP — InvoiceUploadView.post() orchestrates the entire business workflow

views.py:954 — The view creates the batch, creates the audit session, routes to zip/structured/single-file processors, handles async vs sync decisions, finalizes the batch, logs the action, and builds the response. An HTTP handler should only: (1) validate input, (2) call a service, (3) return a response.

S-2: SRP — CustomRuleDefinition model has an evaluate() method

A Django model class whose responsibility is data persistence is also responsible for business logic evaluation. These are two separate concerns. The model should be a data container; evaluation belongs in a RuleEvaluatorService.

O-1: OCP — ValidationService.validate() uses an explicit type dispatch dict

auditing/services/validation_service.py:44:


type_validators = {
    "bank_statement": self._validate_bank_statement,
    "payroll": self._validate_payroll,
    ...
}
Adding a new document type requires modifying this method. It should use a plugin/registry pattern so new document types can register their validators without touching the base class.

O-2: OCP — _process_single_file handles all file types with if/elif chains

Adding a new file type (e.g., XML invoices) requires modifying _process_single_file, _iter_structured_records, ALLOWED_EXT, and ALLOWED_MIME. Each is a different file. There is no single registration point for file type support.

D-1: DIP — _process_single_file instantiates concrete services directly


doc_engine = DocumentEngine(use_ai=True)
ai_engine = FinancialAIEngine(organization_id=org.id, country_code="SA", use_ai=True)
The view hardcodes country_code="SA" — this is not read from the organization's settings. The services cannot be swapped or mocked without patching at the class level.

DRY Violations
DRY-1: _save_audit_event exists in two places

views.py:92 — module-level function
validation_service.py:234 — private static method
Both do the same thing: create an InvoiceAuditEvent with IP extraction. They have slightly different parameter names and IP extraction logic.

DRY-2: _get_vendor_history is duplicated

views.py:507 — uses VendorProfile.objects.get(), returns 5 fields
validation_service.py:205 — uses Invoice.objects.aggregate(), returns 4 different fields
Two functions with the same name, same purpose, different implementations. They will silently produce different vendor risk signals.

DRY-3: Date parsing appears in at least 3 places


# views.py line 172
for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
    ...
# views.py line 358
for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", ...):
    ...
Different format lists, different fallback behavior, no shared utility.

DRY-4: Risk level calculation from score is duplicated

InvoiceValidationService.risk_level_from_score() (validation_service.py:53) — thresholds: 70/40
Likely also in core/services/invoice_validator.py — different thresholds
AuditPipelineV2 stages may have their own thresholds
DRY-5: The Severity TextChoices class is defined 4 times

apps/invoices/models.py — Severity
apps/audit/models.py — AuditFinding.Severity, CustomRuleDefinition.Severity, AuditCase.Priority
All define the same LOW/MEDIUM/HIGH/CRITICAL enum. There is a shared one in apps/invoices/models.py but it is not used by the audit models.

Separation of Concerns Violations
SOC-1: Business logic mixed into views.py

250+ lines of processing code before the first class definition. The functions _process_single_file, _process_zip, _process_structured_upload, all _iter_* functions, _get_vendor_history, _save_canonical_invoice, _update_vendor_profile are all business operations that happen to live in a views file.

SOC-2: Parser logic in views.py

_iter_csv_records, _iter_excel_records, _iter_json_records, _iter_structured_records in views.py:648 — this is file parsing logic. There is already a core/services/parsers/ directory with PDF, Image, Excel, CSV, JSON, and ZIP parsers. The same work is done in two places.

SOC-3: Invoice.generate_zatca_qr() calls an external service from the model

apps/invoices/models.py:233:


def generate_zatca_qr(self):
    from apps.compliance.zatca_qr_service import generate_invoice_qr
    result = generate_invoice_qr(self, ...)
    ...
A model's generate_zatca_qr() should not call a service. It should just hold the QR data. Calling it from the model means you cannot generate a QR code without also mutating model state, cannot generate a preview QR, and cannot test QR generation without a full database invoice.

SOC-4: AuditCase.save() generates a business identifier

The case_number generation in save() is business logic (case numbering conventions, year-based sequencing). It belongs in a service's create_case() method, not in a model's save().

Django Architecture Violations
DA-1: No proper settings split

Two settings systems exist simultaneously:

finai_backend/settings.py — monolithic single file (200+ lines, currently active based on git status modifications)
finai_backend/settings/ directory with base.py, production.py, test.py
It is not clear which is canonical. The monolith has DEBUG = os.environ.get("DEBUG", "True") == "True" — the default is True, which is dangerous if DEBUG is accidentally not set in a production environment.

DA-2: Product branding strings in settings.py


PRODUCT_NAME = "Tadgeeg AI"
COMPANY_NAME = "Get Solution Company"
PRODUCT_TAGLINE_AR = "منصة الذكاء الاصطناعي للتدقيق المالي والامتثال"
Django settings are for infrastructure configuration. String constants belong in apps/core/constants.py or an app config.

DA-3: Module-level service instantiation in views.py

views.py:59:


normalizer = NormalizationService()
This runs at import time. If NormalizationService.__init__ ever does something expensive (opens a file, connects to a service), every Django startup pays the cost. It also makes mocking harder.

DA-4: Celery tasks importing from views

tasks.py:64: from apps.invoices.views import _process_structured_rows_chunk

This inverts the dependency. Tasks should call services; views should dispatch tasks. This will cause import errors if the Django routing layer is not fully initialized before the task worker starts.

DA-5: InvoiceValidationResult has a flat schema for 30 rule results

models.py:320 — 30 boolean columns. Every time a rule is added or renamed, this requires a migration and a code change in every serializer, test, and query that references these fields. The data is inherently variable-length and should be:


validation_results = models.JSONField(default=list)
# [{"rule_code": "INV-001", "passed": True, "detail": "..."}, ...]
DA-6: apps/auditing/ duplicates services already in core/services/ and apps/audit_engine/

The apps/auditing/services/ directory contains:

validation_service.py — yet another validator
normalization_service.py — yet another normalizer
ocr_service.py — yet another OCR service
parser_service.py — yet another parser service
These overlap with core/services/normalization.py, core/services/ocr_service.py, and apps/audit_engine/services/parsers/. There are effectively three parallel implementations of the same infrastructure.

D. Refactoring Plan
Immediate Fixes (Do Before Any New Feature)
#	Action	Risk
1	Fix AuditCase.save() race condition — use select_for_update() or a DB sequence	Production data corruption
2	Fix CustomRuleDefinition.save() — wrap version increment in transaction.atomic()	Silent version corruption
3	Move _process_structured_rows_chunk out of views.py into InvoiceProcessingService	Celery import bomb
4	Set DEBUG = os.environ.get("DEBUG", "False") == "True" (flip default)	Accidental prod debug mode
5	Add DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField" explicitly	Django 4.x warning
6	Delete the settings split ambiguity — pick one canonical settings entry point	Operational confusion
Medium-Priority Refactors (Before Scale-Up)
#	Action	Benefit
7	Extract _process_single_file into InvoiceIngestionService	Testability, reuse from tasks
8	Collect all CSV/Excel/JSON iteration into core/services/parsers/	Single file type registration point
9	Replace InvoiceValidationResult's 30 boolean fields with a single JSONField	Schema decoupled from rule set
10	Deduplicate Severity choices into a single core.constants module	One change point
11	Consolidate _save_audit_event into a single AuditEventService.record()	No silent divergence
12	Remove Invoice.generate_zatca_qr() — move logic to ZATCAService	Model is pure data
13	Consolidate _get_vendor_history into VendorIntelligenceService	Single vendor data source
14	Create a RISK_THRESHOLDS constants object and replace all magic numbers	One place to tune risk parameters
Long-Term Architectural Improvements
#	Action	Benefit
15	Define one canonical audit pipeline and deprecate the other two	Predictable audit results
16	Merge apps/audit/, apps/auditing/, apps/audit_engine/ into apps/audit/ with sub-packages	Module clarity
17	Make ValidationService and CustomRuleDefinition.evaluate() use a RuleEvaluator protocol	Open/Closed compliance
18	Move apps/auditing/services/ overlap into core/services/	Single infrastructure layer
19	Replace ALLOWED_MIME / ALLOWED_EXT dicts in views with a FileTypeRegistry class	Open/Closed for file types
20	Add database-level constraints to enforce org-scoping at the DB, not just application layer	Defense in depth
E. Proposed Target Architecture
Recommended Folder Structure

tadgeeg/
├── finai_backend/
│   ├── settings/
│   │   ├── base.py           ← Single canonical base
│   │   ├── production.py
│   │   └── test.py
│   ├── urls.py
│   └── celery.py
│
├── core/
│   ├── constants.py          ← All shared enums, thresholds, magic numbers
│   ├── domain/
│   │   ├── result.py         ← ServiceResult (already good)
│   │   └── events.py         ← Domain event types
│   ├── services/
│   │   ├── parsers/          ← ALL file parsers (PDF, image, CSV, Excel, JSON, ZIP)
│   │   ├── extraction/       ← OCR + AI extraction
│   │   ├── validation/       ← Core validation rules + pipeline
│   │   ├── risk/             ← Risk scoring engine
│   │   └── compliance/       ← ZATCA, VAT
│   └── utils/
│
├── apps/
│   ├── authentication/       ← User, Organization, RBAC
│   ├── invoices/
│   │   ├── models.py
│   │   ├── serializers.py
│   │   ├── views.py          ← ONLY HTTP handling (thin)
│   │   ├── urls.py
│   │   ├── tasks.py          ← ONLY Celery wrappers
│   │   └── services/
│   │       ├── ingestion.py        ← InvoiceIngestionService (owns _process_single_file)
│   │       ├── validation.py       ← InvoiceValidationService
│   │       ├── vendor.py           ← VendorIntelligenceService
│   │       └── batch.py            ← InvoiceBatchService
│   ├── audit/
│   │   ├── models.py
│   │   ├── views.py
│   │   ├── tasks.py
│   │   ├── pipeline/
│   │   │   ├── v2/           ← V2 pipeline stages (already good)
│   │   │   └── stages/
│   │   ├── rules/            ← Rule registry, rule definitions
│   │   └── services/
│   │       ├── session.py
│   │       ├── finding.py
│   │       └── case.py       ← case_number generation here, not in model
│   ├── documents/
│   ├── analytics/
│   ├── compliance/
│   ├── reports/
│   └── [remaining thin apps]
Service Layer Contract
Every service function should:

Return ServiceResult (already defined in core/domain/result.py — use it consistently)
Accept domain objects or IDs, never raw request objects
Never import from views.py or tasks.py
Be callable from both views and Celery tasks without modification
Where Business Logic Lives
Logic	Current (Wrong)	Target
Invoice field normalization	views.py:_process_single_file	InvoiceIngestionService.process()
Vendor history lookup	views.py + `validation	
Now I have enough to write the full architectural review. Let me deliver it:

Tadgeeg AI — Enterprise Architecture Review
Date: 2026-04-09 | Reviewer: Senior Software Architect | Codebase: Django 4.2, ~29 apps, ~150+ Python files

A. Executive Summary
Dimension	Score	Notes
Overall Health	5.2 / 10	Functional but structurally risky
Architecture	4.5 / 10	Duplicate pipelines, God Functions
Clean Code	5.5 / 10	Good naming; terrible function size
SOLID	4.0 / 10	SRP violations everywhere
DRY	4.5 / 10	3–4 copies of core logic
Testability	5.0 / 10	Hard to unit test; interwoven
Scalability	6.0 / 10	Async exists but pipeline design limits it
Main Architectural Risks
Three concurrent audit pipelines fire per invoice — race conditions, triple cost, no source of truth
_process_single_file is a 250-line God Function in views.py — untestable without HTTP, unkillable
Business logic leaks into models, views, and Celery tasks — scattered, duplicated, untestable
Dual settings architecture (settings.py vs settings/) — undefined production load path
InvoiceValidationResult has 30+ boolean fields — will break every time a rule is added
Main Maintainability Risks
Adding a new audit rule requires changes in 4+ files across 3 apps
Any change to risk scoring logic must be replicated in 3+ places
Celery task imports a private function directly from views.py — tight coupling
Main Scalability Risks
Each invoice triggers up to 3 synchronous OpenAI API calls
No caching layer for vendor history or rule results
VendorProfile is updated on every invoice save via a function called from views
B. Critical Problems
B1. Three Parallel Audit Pipelines Per Invoice (CRITICAL)
In apps/invoices/views.py:414-445, _process_single_file fires three audit systems in sequence on the same invoice:


# Step 7a — Legacy audit engine
run_audit(analysis.to_dict(), organization_id=org.id, invoice_id=invoice.id, persist=True)

# Step 7b — V2 rule engine (async Celery)
run_audit_task.delay(document_id=str(invoice.id), document_type="sales_invoice", ...)

# Step 7c — 30-rule ZATCA validation
ValidationPipelineService.validate_invoice(invoice=invoice, organization=org, ...)
Why it is dangerous:

Triple OpenAI/compute cost per document
AuditFinding records created by all three; no discriminator tells you which is canonical
The Celery task runs after the HTTP response is returned, creating race conditions on invoice.risk_score
The 30-rule ZATCA result drives the final risk score, but the Celery job may overwrite it asynchronously
Impossible to test the end state deterministically
B2. God Function in views.py (CRITICAL)
apps/invoices/views.py:237–504 — _process_single_file is 268 lines of sequential steps:

File hash + audit session deduplication
Invoice DB creation
Document engine (MIME, OCR)
AI extraction (GPT-4o)
Normalization
30+ field assignments to Invoice model
_safe_decimal / _safe_date defined inside the function (inline closures)
Financial AI engine
Audit engine (legacy)
Rule engine (new, async dispatch)
ZATCA validation
Risk score merge
Canonical data save
Vendor profile update
Why it is dangerous:

Zero testability without a real file and database
Any failure anywhere crashes the entire processing flow
The inline _safe_decimal, _safe_date closures cannot be reused or tested in isolation
Adding a 31st rule means modifying this monster function
B3. File Parsing Logic in views.py (CRITICAL)
Lines 639–928 of views.py contain: _iter_csv_records, _iter_excel_records, _iter_json_records, _iter_structured_records, _process_structured_rows_chunk, _process_structured_upload, _detect_csv_delimiter, _process_zip.

That is a complete file-parsing subsystem inside a Django view file. This logic belongs in core/services/parsers/ and is in fact partially duplicated there (see apps/audit_engine/services/parsers/).

B4. Celery Task Imports Private View Function (CRITICAL)
apps/invoices/tasks.py:64:


from apps.invoices.views import _process_structured_rows_chunk
A Celery worker imports a private helper function from a Django view. This means:

The entire view module is loaded in the Celery process
Circular import risk: views → tasks → views
Private API leakage — _process_structured_rows_chunk is now a public contract between two modules
B5. InvoiceValidationResult with 30 Boolean Fields (HIGH)
apps/invoices/models.py:320–380: Each of the 30 rules has a dedicated boolean column. Adding rule 31 requires a database migration, model change, serializer change, and admin change. This is the "Parallel Conditionals" anti-pattern applied to a database schema.

B6. Race Condition in AuditCase.save() (HIGH)
apps/audit/models.py:262–268:


count = AuditCase.objects.filter(organization=self.organization).count()
year = datetime.datetime.now().year
self.case_number = f"CASE-{year}-{count + 1:04d}"
Under concurrent creates for the same organization, two cases will get the same case_number. case_number has unique=True, so one of the inserts will silently fail in production.

B7. CustomRuleDefinition.evaluate() in a Model (HIGH)
apps/audit/models.py:358–417: A Django Model executes business rule evaluation, including importing Invoice and running database queries (InvoiceModel.objects.filter(...).count() > 1). This is a textbook fat-model violation and makes the model impossible to test without a full database.

C. Violations by Principle
C1. Clean Code Violations
Location	Violation	Severity
views.py:237–504	_process_single_file — 268 lines, 10+ responsibilities	Critical
views.py:347–353	_safe_decimal, _safe_date defined inside another function	Medium
views.py:62–132	6 module-level delegates (_to_float, _risk_level_from_score, etc.) that simply call InvoiceValidationService	Medium
models.py:279	status = models.BatchStatus if False else models.CharField(...) — dead code in a field declaration	Low
validation_service.py:54	Magic numbers 78.0, 72.0, 58.0 with no named constant	Medium
models.py:434–443	vendor_risk_score property returns float(self.risk_score or 0) — identical to the field	Low
models.py:438	average_transaction_value property is a pointless alias for avg_invoice_amount	Low
Settings	_SECRET_KEY_FALLBACK = "change-me-in-production-use-long-random-string" — the fallback message is itself visible in code	Low
C2. SOLID Violations
Single Responsibility Principle:

InvoiceUploadView.post() handles validation, batch creation, session creation, file routing (zip/csv/excel/json/pdf), async dispatch, sync processing, response building — all in one method
_process_single_file as documented above
CustomRuleDefinition.evaluate() — model that is also a rule evaluator and ORM query runner
apps/invoices/views.py is simultaneously: a REST endpoint, a file parser, an ETL pipeline, a risk scoring engine, and a report builder
Open/Closed Principle:

Adding a new file type to the upload pipeline requires modifying _process_single_file, _iter_structured_records, _process_zip, and ALLOWED_EXT/ALLOWED_MIME constants — four edit points, zero extension points
Adding a new audit rule requires modifying InvoiceValidationResult (new boolean field), core/services/invoice_validator.py (add rule logic), migration, serializer, admin — no plugin/registration mechanism
Dependency Inversion Principle:

_process_single_file directly instantiates DocumentEngine(use_ai=True), FinancialAIEngine(organization_id=org.id, ...) — hard-wired concrete classes, impossible to swap in tests
InvoiceValidationService.revalidate() directly calls run_all_rules from core.services.invoice_validator — no abstraction, concrete dependency
Interface Segregation Principle:

InvoiceDetailSerializer uses fields = "__all__" — exposes all 60+ fields to every consumer regardless of what they need
VendorProfileSerializer lists all fields in both fields and read_only_fields = fields — redundant and error-prone
C3. DRY Violations
Four copies of validation logic:

File	Class	What it validates
core/services/invoice_validator.py	run_all_rules()	30 ZATCA rules against Invoice model
core/services/validation_pipeline.py	ValidationPipelineService	Orchestrates the above + persists results
apps/invoices/services/validation_service.py	InvoiceValidationService	Risk merging + revalidation (calls the above)
apps/auditing/services/validation_service.py	ValidationService	Separate field/date/total validation for AI documents
Two copies of _get_vendor_history:

views.py:507–520: Queries VendorProfile model
validation_service.py:205–230: Queries Invoice model via aggregation
They return different key names (invoice_count vs transaction_count) and different data shapes.

Two copies of _save_audit_event:

views.py:92–101: Module-level function
validation_service.py:233–251: InvoiceValidationService._save_audit_event
Both create InvoiceAuditEvent records with slightly different IP extraction logic.

Two parser subsystems:

apps/audit_engine/services/parsers/ — PDF, CSV, Excel, JSON, Image parsers
core/services/parsers/ (referenced in document_engine) — separate implementations
apps/auditing/services/parser_service.py — a third parser service
views.py:639–728 — inline CSV/Excel/JSON iteration (a fourth implementation)
Two risk-level-from-score functions:

InvoiceValidationService.risk_level_from_score() uses >=70 → high, >=40 → medium
The pipeline V2 stages use different thresholds
Duplicate _safe_decimal / _safe_date utilities:

Defined inline inside _process_single_file
Similar logic in NormalizationService.normalize()
Similar logic in ValidationService._validate_dates()
C4. Separation of Concerns Violations
Where logic lives	What logic lives there	Where it should be
views.py	CSV/Excel/JSON/ZIP parsing	core/services/parsers/
views.py	Risk score merging	core/services/scoring/
views.py	Vendor profile update dispatch	apps/invoices/services/
views.py	Canonical data saving	core/services/canonical_mapper.py
models.py (AuditCase)	Case number generation	Service or signal
models.py (Invoice)	ZATCA QR generation via generate_zatca_qr()	apps/compliance/zatca_qr_service.py
models.py (CustomRuleDefinition)	Rule evaluation + ORM queries	Rule executor service
tasks.py	Business process orchestration (imports _process_structured_rows_chunk from views)	Dedicated processor service
settings.py	Sentry SDK initialization at module import time	Should be in AppConfig.ready()
views.py:60	normalizer = NormalizationService() as module-level singleton	Dependency injection
C5. Django Architecture Violations
Fat views / missing service layer:
The entire invoice processing pipeline is embedded in views.py instead of a proper service. InvoiceUploadView.post() is the entry point for HTTP and the entire ETL pipeline. Celery tasks have to import from it directly as a result.

Settings dualism:
Both finai_backend/settings.py and finai_backend/settings/ exist. Only one can be DJANGO_SETTINGS_MODULE. The other is vestigial and creates confusion about which settings are active in production vs test. The settings_canonical.py file adds a third variant.

Transaction boundaries:
_process_single_file performs multiple invoice.save() calls (at step 1, again at step 6 population, again after risk merge, again at step 9 — four saves to the same record). No outer transaction.atomic() wraps the whole unit of work. If step 7 fails, the database has a half-populated Invoice with status=PROCESSING.

Celery task naming:
The task is declared as name="invoices.process_invoice_rows_chunk" but the Python function is named process_invoice_rows_chunk_task — the _task suffix is the convention for Python function name but the registered Celery name doesn't match. This is a minor issue but causes confusion in monitoring.

settings.py sets DEBUG = os.environ.get("DEBUG", "True") == "True":
The default is "True" — debug mode on by default. This is a footgun if the DEBUG env variable is missing in a production deployment.

D. Refactoring Plan
Immediate Fixes (1–2 weeks)
#	Action	Risk	Impact
1	Wrap _process_single_file in transaction.atomic() to prevent half-saved invoices	Low	High
2	Extract _safe_decimal, _safe_date to core/utils/coerce.py	Low	Medium
3	Move _get_vendor_history from views.py and kill the duplicate in validation_service.py	Low	Medium
4	Merge the two _save_audit_event implementations into one in core/utils/audit.py	Low	Medium
5	Fix AuditCase.save() race condition using select_for_update() or database sequence	Medium	Critical
6	Fix DEBUG default to "False" in settings.py	Low	Critical
7	Delete the status = models.BatchStatus if False else models.CharField(...) dead code	Low	Low
8	Add unique=True + db_index=True guards on AuditCase.case_number if not already	Low	High
Medium-Priority Refactors (1–2 months)
#	Action	Risk	Impact
9	Extract _process_single_file into InvoiceProcessingService with injected dependencies	Medium	Critical
10	Move all CSV/Excel/JSON/ZIP iteration out of views.py into core/services/parsers/	Medium	High
11	Move CustomRuleDefinition.evaluate() into a CustomRuleEvaluator service	Medium	High
12	Move Invoice.generate_zatca_qr() out of model into apps/compliance/zatca_qr_service.py	Medium	Medium
13	Consolidate the four validation services into a single InvoiceValidationService	High	Critical
14	Eliminate one or two of the three per-invoice audit pipeline calls	High	Critical
15	Replace InvoiceValidationResult 30-boolean schema with a JSON rule_results array	High	High
16	Move the circular import from tasks.py → views.py into a shared processors.py	Medium	High
17	Consolidate finai_backend/settings.py and finai_backend/settings/ into a single path	Low	Medium
Long-Term Architectural Improvements (3–6 months)
#	Action	Impact
18	Establish a canonical single-pipeline entry point, deprecate the legacy two	Critical
19	Implement proper DI for DocumentEngine and FinancialAIEngine (injectable via context)	High
20	Replace the InvoiceValidationResult model with an EAV or JSON-based RuleResult model	High
21	Add circuit breakers around OpenAI calls (currently a bare try/except with fallback)	High
22	Introduce proper domain events for invoice state transitions instead of scattered AuditEvent creates	High
E. Proposed Target Architecture

tadgeeg/
├── core/
│   ├── domain/
│   │   ├── result.py            ✅ Already exists — keep
│   │   ├── invoice.py           NEW: Invoice value object / DTO
│   │   └── rule_result.py       NEW: Replaces 30 boolean fields
│   ├── services/
│   │   ├── parsers/             ← ALL parsing lives here (PDF/CSV/Excel/ZIP/JSON)
│   │   ├── extraction/          ← OCR + AI extraction
│   │   ├── validation/          ← SINGLE validation entry point
│   │   ├── scoring/             ← SINGLE risk scoring service
│   │   └── pipeline/            ← SINGLE orchestrator
│   └── utils/
│       ├── coerce.py            NEW: _safe_decimal, _safe_date, _to_float
│       └── audit.py             ✅ Already exists — consolidate here
│
├── apps/
│   ├── invoices/
│   │   ├── models.py            ← Thin models only, NO business logic
│   │   ├── serializers.py       ← Use explicit field lists, NO __all__
│   │   ├── views.py             ← Thin: validate request, delegate to service
│   │   └── services/
│   │       ├── upload_service.py    ← InvoiceUploadService (replaces _process_single_file)
│   │       ├── processor.py         ← InvoiceProcessor (single file processing)
│   │       └── vendor_intelligence.py ✅ Already exists
│   │
│   ├── audit/
│   │   ├── models.py            ← Remove evaluate() from CustomRuleDefinition
│   │   └── services/
│   │       └── rule_evaluator.py ← CustomRuleEvaluator extracted from model
│   │
│   └── rule_engine/
│       └── pipeline/v2/         ← THE ONE PIPELINE to rule them all
Service Boundaries:

InvoiceUploadService — HTTP boundary: validates request, creates batch/session, delegates to processor
InvoiceProcessor — Orchestrates stages with injected dependencies, wrapped in transaction.atomic()
DocumentParserService — Receives file bytes, returns structured text (replaces 4 parallel parser subsystems)
FinancialExtractionService — GPT-4o + Tesseract extraction (replaces invoice_ai_service)
InvoiceValidationService — Single validator (replaces 4 services)
RiskScoringService — Single risk scorer (replaces scattered merge logic)
AuditPipelineV2 — The authoritative audit pipeline, called by processor
Business logic should live in:

core/services/ for domain-agnostic logic (parsing, scoring, extraction)
apps/<app>/services/ for domain-specific logic
Never in views, models, serializers, signals, or admin
F. File-by-File Review
apps/invoices/views.py
Size: ~1,200 lines

What is wrong: This is the worst file in the codebase. It is simultaneously a REST controller, a file parser, an ETL pipeline, a risk scoring engine, and a utility library.

Specific problems:

_process_single_file (line 237): 268-line God Function with 10 responsibilities
Lines 639–928: Complete file-parsing subsystem (CSV, Excel, JSON, ZIP) that duplicates core/services/parsers/
Module-level normalizer = NormalizationService() singleton (line 59)
6 wrapper functions (lines 117–132) that add zero value — just call through to InvoiceValidationService
_coerce_review_value (line 162): date parsing with 4 format fallbacks duplicates core/utils/coerce that should exist
How to improve: This file should be < 200 lines. All logic below class InvoiceUploadView belongs in services.

apps/invoices/models.py
What is wrong:

Invoice has 60+ fields — vendor info, financial amounts, document quality, accounting linkage, workflow, AI risk, IAS 7 classification, soft delete. This model is a denormalized mega-table.
Invoice.generate_zatca_qr() (line 233): Model method that calls an external compliance service, performs side effects (saving to DB via self.qr_code_image =), and returns a dict. This is service-layer code in a model.
qr_code_image = models.TextField() (line 84): Stores a base64-encoded PNG in a text column. Should be a FileField or stored in object storage with a URL reference.
InvoiceValidationResult (line 320): 30+ boolean columns. Every new rule is a migration.
InvoiceBatch.status field (line 279): models.BatchStatus if False else models.CharField(...) — dead code in production.
How to improve:

Extract generate_zatca_qr() to apps/compliance/zatca_qr_service.py
Replace InvoiceValidationResult with a rule_results: JSONField or a normalized RuleResult model
Store QR as a file, not a text blob
apps/audit/models.py
What is wrong:

AuditCase.save() (line 262): Non-atomic case number generation is a race condition
CustomRuleDefinition.evaluate() (line 358): 60-line business method in a model, including ORM queries against Invoice
AuditFinding does not inherit SoftDeleteModel — inconsistent deletion strategy vs AuditSession and AuditCase
How to improve:

Extract evaluate() to a CustomRuleEvaluator service
Use a select_for_update() counter or a Sequence for case number
Make AuditFinding soft-deletable for consistency
apps/invoices/tasks.py
What is wrong:

Line 64: from apps.invoices.views import _process_structured_rows_chunk — a Celery task imports a private function from a view. This is a layering violation and circular dependency risk.
_finalize_batch_if_ready (line 15): Is a module-level utility that is not a Celery task. Should live in a service.
How to improve:

Move _process_structured_rows_chunk to apps/invoices/services/processor.py
Tasks should only: load models, call services, handle retries
apps/invoices/services/validation_service.py
What is good: This is actually well-structured. ServiceResult pattern, static methods, single class. The extraction from views.py was done correctly.

What is wrong:

Magic numbers 78.0, 72.0, 58.0 (lines 80–84) — define DUP_RISK_FLOOR = 78.0 etc. as named constants
_get_vendor_history (line 205) queries Invoice directly — there's another copy in views.py that queries VendorProfile. Both should be eliminated in favor of a single VendorHistoryService
_save_audit_event (line 233) is duplicated from views.py
core/domain/result.py
What is good: This is excellent. ServiceResult is clean, well-documented, and consistently used. Keep it and extend its adoption to all services.

core/mixins.py
What is good: SoftDeleteModel, SoftDeleteManager, OrganizationQuerySetMixin — all well-designed and properly abstract. The pattern of leaving deleted_by for subclasses to define with their own related_name is the correct approach.

What is wrong: Nothing significant. Minor: restore() does not record who restored — consider adding an optional user param that logs to audit trail.

finai_backend/settings.py
What is wrong:

DEBUG = os.environ.get("DEBUG", "True") == "True" — defaults to True in production if env var missing
Sentry SDK initialized at module import time (lines 18–36) instead of in AppConfig.ready()
Both finai_backend/settings.py and finai_backend/settings/ exist — unclear which is active
How to improve:

Change default to "False"
Move Sentry init to AppConfig.ready() or a dedicated apps/telemetry/apps.py
Delete or consolidate the duplicate settings directory
apps/rule_engine/pipeline/v2/pipeline.py
What is good: AuditPipelineV2 is the best-designed piece of the codebase. Stages as injectable classes, idempotency guard, dry-run support, clean PipelineContext, version tracking. This is the architecture the rest of the codebase should aspire to.

What is wrong: It's being bypassed. Despite being "V2 / V3.0", the main invoice upload still calls the legacy run_audit() and the 30-rule ZATCA validator directly (Steps 7a and 7c in _process_single_file). V2 is only called as an async fire-and-forget (Step 7b). The result from V2 never influences the synchronous risk score.

G. Safe Refactor Strategy
Phase 0: Safety Net (before any refactoring)
Write tests for the following before touching anything:

_process_single_file end-to-end with a fixture PDF — validate Invoice fields, InvoiceValidationResult, AuditFinding counts
InvoiceValidationService.merge_risk_assessment() with all score combinations
AuditCase concurrent creation — test for case number uniqueness under parallel calls
CustomRuleDefinition.evaluate() for each ConditionType
Coverage target: 70% on apps/invoices/, apps/audit/, core/services/ before proceeding

Phase 1: Extract Without Breaking (Week 1–3)
These are pure extractions — move code without changing behavior:

Extract _safe_decimal, _safe_date, _to_float → core/utils/coerce.py
Extract _save_audit_event → core/utils/audit.py (single canonical version)
Extract _get_vendor_history → apps/invoices/services/vendor_intelligence.py (already exists — add this)
Extract _iter_csv_records, _iter_excel_records, _iter_json_records, _detect_csv_delimiter → core/services/parsers/structured_parser.py
Extract _process_structured_rows_chunk, _process_structured_upload, _process_zip → apps/invoices/services/processor.py
Fix the Celery import: change tasks.py to import from apps/invoices/services/processor.py
Phase 2: Wrap in Transactions + Fix Race Conditions (Week 3–4)
Wrap _process_single_file in transaction.atomic() — minimum 1-line change, maximum impact
Fix AuditCase.case_number generation with select_for_update() or a DB sequence
Add try/finally cleanup in _process_single_file to set status=FAILED if an unhandled exception escapes
Phase 3: Service Extraction (Month 2)
Create InvoiceProcessingService that absorbs _process_single_file with injected DocumentEngine and FinancialAIEngine
Create a thin InvoiceUploadService that handles HTTP-layer concerns (batch creation, session creation, file routing) and delegates to InvoiceProcessingService
Reduce InvoiceUploadView.post() to < 30 lines
Move CustomRuleDefinition.evaluate() to apps/audit/services/rule_evaluator.py
Phase 4: Pipeline Consolidation (Month 3)
Make AuditPipelineV2 the only audit pipeline — retire the legacy run_audit() call
Wire V2 result back into the synchronous risk score (today it's fire-and-forget)
Retire ValidationPipelineService as a direct call — route through V2's RuleEngineStage
Keep the ZATCA 30-rule validator as a stage within V2, not a separate call
Phase 5: Schema Cleanup (Month 4–6)
Replace InvoiceValidationResult's 30 booleans with rule_results: JSONField
Write a data migration to convert existing boolean records to JSON format
Consolidate finai_backend/settings.py and finai_backend/settings/ into one path
Top 20 Highest-Value Refactor Actions
Rank	Action	Value	Effort
1	Wrap _process_single_file in transaction.atomic()	Critical safety	1 line
2	Fix AuditCase.case_number race condition	Critical bug	1 hour
3	Fix DEBUG default to "False" in settings	Security	1 line
4	Fix Celery task circular import from views	Architecture	1 hour
5	Extract _process_single_file into InvoiceProcessingService	Testability	1 day
6	Eliminate two of three per-invoice audit pipeline calls	Cost + correctness	1 week
7	Extract all file parsing from views.py into core/services/parsers/	SRP	2 days
8	Move CustomRuleDefinition.evaluate() to a service	Fat model	2 hours
9	Consolidate 4 validation services into one	DRY	1 week
10	Consolidate 2 _get_vendor_history copies	DRY	2 hours
11	Consolidate 2 _save_audit_event copies	DRY	1 hour
12	Replace InvoiceValidationResult 30-boolean schema	Extensibility	1 week
13	Move Invoice.generate_zatca_qr() out of model	SRP	2 hours
14	Make AuditPipelineV2 the single authoritative pipeline	Architecture	2 weeks
15	Add ServiceResult return type to all services (extend core.domain.result)	Contracts	3 days
16	Extract _safe_decimal, _safe_date to core/utils/coerce.py	DRY + testability	1 hour
17	Replace fields = "__all__" in InvoiceDetailSerializer	Security + SRP	30 min
18	Consolidate duplicate settings paths	Clarity	1 hour
19	Remove dead code: status = models.BatchStatus if False else ...	Clarity	1 min
20	Name risk-score constants: DUP_RISK_FLOOR = 78.0 etc.	Readability	30 min
Final Verdict
The codebase is functional and feature-rich, with genuine engineering thought in places — AuditPipelineV2, ServiceResult, SoftDeleteModel, and OrganizationQuerySetMixin are all solid. The ZATCA/GCC compliance domain knowledge is well-encoded.

The structural debt is concentrated in two places: apps/invoices/views.py (a 1,200-line file that should be 200) and the three-pipeline problem (the same invoice processed by three overlapping audit systems simultaneously). Fix those two things and the codebase's quality score rises from 5.2 to approximately 7.5 without touching any other file.

The system is not ready for scale-up in its current form. Adding AI engines, ERP connectors, or workflow automation on top of the existing _process_single_file architecture will create an unmaintainable branching tree of conditions. The V2 pipeline design is already present and is the right foundation — it just needs to become the only foundation.