# VerifyNG Master Development Plan & Roadmap

## A. Project Overview and Objectives
VerifyNG is Nigeria's first public, accessible trust and safety platform designed to address three primary use cases:
1. **CHECK**: Search individuals, artisans, agents, or businesses by phone number, bank account, NIN hash, or BVN hash to retrieve factual trust summaries and public report histories in under 60 seconds.
2. **REPORT**: Submit verified allegations against fraudsters or scam operations with mandatory reporter identity verification, structured evidence uploads, and a fair right-of-response / dispute process.
3. **VERIFY**: Build portable, digital trust profiles for workers, artisans, and individuals containing confirmed identity facts, employment histories, and verified credentials.

### Primary Business & Technical Objectives
- **Accessibility**: Provide standard web, mobile-responsive, and WhatsApp-accessible lookup and reporting flows.
- **Safety & Compliance**: Enforce strict data minimisation, cryptographic representation of sensitive identifiers (NIN/BVN), and NDPR compliance.
- **Neutrality**: Present allegations through a neutral moderation lifecycle without making unsubstantiated legal claims of guilt.
- **Scalability**: Build on Django 5.x, Django Ninja, PostgreSQL 18, and Alpine.js / Bootstrap 5 with zero build step overhead.

---

## B. Final Approved Project Architecture

The application is structured as a unified Django monolith directly at the project root (`C:\python_project\verifyNG\`):

```text
verifyNG/
├── manage.py
├── requirements.txt
├── .env
├── .env.example
├── .gitignore
├── CLAUDE.md
│
├── config/             # Django settings, URLs, WSGI, ASGI
├── users/              # Accounts, registration, auth, profiles, roles
├── public_website/     # Public marketing site, landing pages, signup/login entry points
├── dashboard/          # Authenticated user dashboard & app interface
├── api/                # Django Ninja REST API & webhooks
├── identities/         # SubjectEntity (Person/Business) & Hashed Identifiers
├── reports/            # Fraud/scam/misconduct reports & moderation workflows
├── verification/       # VerifyNG checks & report-generation utilities
├── integrations/       # External identity, messaging, & payment abstractions
├── core/               # Shared security, permissions, audit logs, & utilities
├── templates/          # SSR Django templates (public & dashboard)
└── static/             # Locally managed CSS, JS, & image assets
```

### Architectural Principles
- **No `backend/` subfolder**: The project root is the top-level directory for Django.
- **App-Local Migrations**: Django migrations reside exclusively in their respective app `migrations/` directories (e.g., `users/migrations/`). No central/global migrations folder.
- **Built-in Django Admin**: Django's native admin interface remains available via `config/urls.py` and is configured through `admin.py` in each app. The `dashboard/` app is strictly for end-user web applications.
- **Zero Build Step Frontend**: Bootstrap 5 and Alpine.js are hosted locally in `static/` and rendered via Django templates without Webpack/Vite build toolchain complexity.

---

## C. Development Principles and Workflow

### Master Plan vs. Implementation Batches
- **MASTER PLAN (This Document)**: The macro-level architectural roadmap outlining project phases, requirements, dependencies, and overall progress.
- **IMPLEMENTATION BATCHES**: Micro-level, highly specific coding steps detailing exact files to create, update, or delete, complete with Windows PowerShell commands and explicit expected test results.

### Step-by-Step Batch Execution Protocol
Implementation follows a strict, controlled loop:
1. **Plan & Present**: The assistant presents a single, isolated implementation batch.
2. **Human Apply**: The human developer applies code changes in VS Code and executes commands in Windows PowerShell.
3. **Test & Verify**: Run Django management commands, test suites, and inspect browser / API behavior.
4. **Fix Errors**: If an error occurs, halt immediately and resolve the current batch.
5. **Human Confirmation**: The human developer explicitly confirms success by typing **"NEXT"**.
6. **Proceed**: Only upon receiving "NEXT" does the assistant generate the subsequent batch.

---

## D. Current Project Status

- [x] **Initial Project Inspection**: COMPLETED
- [x] **Project Structure Reorganization (Batch 1)**: COMPLETED (`backend/` removed, apps renamed to `users/` and `public_website/`, stubs created for `dashboard/`, `verification/`, `core/`)
- [x] **PostgreSQL 18 Configuration**: COMPLETED (Local `.env` configured, Django connected to PostgreSQL 18, initial migrations applied cleanly)
- [ ] **Domain Model Architecture & Redesign**: IN PROGRESS (Batch 3.1 & Batch 3.2 Completed: SubjectEntity, Identifier, BusinessProfile, FraudReport, ReportEvidence, Dispute, AuditLog refined and migrated)
- [ ] **Authentication & User Roles (RBAC)**: NOT STARTED
- [ ] **Security, Privacy & Audit Architecture**: NOT STARTED
- [ ] **Redis Caching & Background Jobs Evaluation**: NOT STARTED
- [ ] **Core Application & API Features**: NOT STARTED
- [ ] **Verification Workflows & PDF Reports**: NOT STARTED
- [ ] **Full Test Suite & QA**: NOT STARTED
- [ ] **Production Readiness & Hardening**: NOT STARTED

---

## E. Major Development Phases

### Phase 1 — Existing Project Inspection & Restructuring
- **Objective**: Audit original code, eliminate obsolete Docker files, and reorganize the repository into a clean root-level Django architecture.
- **Major Tasks**: Move files out of `backend/`, rename `accounts` → `users`, rename `public_site` → `public_website`, establish app stubs.
- **Deliverables**: Root-level project tree, updated master plan.
- **Dependencies**: None.
- **Testing**: Directory tree verification via PowerShell.
- **Status**: **COMPLETED**

---

### Phase 2 — PostgreSQL 18 & Database Foundation
- **Objective**: Establish the primary local PostgreSQL 18 connection using `django-environ` and `.env` credentials, removing fallback settings.
- **Major Tasks**:
  1. Create `.env.example` and local `.env` with PostgreSQL 18 connection string.
  2. Update `config/settings.py` to securely read `.env`.
  3. Audited existing migrations for app compatibility (`users`, `identities`, `reports`).
  4. Created security `.gitignore` protecting secrets.
  5. Run `python manage.py check` and `python manage.py migrate` against local PostgreSQL 18.
- **Deliverables**: Verified database connection, applied PostgreSQL tables, working environment files, security `.gitignore`.
- **Dependencies**: Phase 1.
- **Testing**: `python manage.py migrate` execution against local PostgreSQL 18, database table creation.
- **Status**: **COMPLETED**

---

### Phase 3 — Database & Domain Model Architecture
- **Objective**: Design and build domain models reflecting real-world entities, identifiers, reports, disputes, and evidence.
- **Major Tasks**:
  1. Refine `identities.SubjectEntity` (`person` or `business`). [COMPLETED]
  2. Refine `identities.Identifier` (`phone`, `nin`, `bvn`, `account`) with database indexing. [COMPLETED]
  3. Implement `identities.BusinessProfile` and Admin registration. [COMPLETED]
  4. Refine `reports.FraudReport` neutral moderation lifecycle states (`submitted`, `under_review`, `published`, `disputed`, `resolved`, `rejected`, `restricted`, `archived`). [COMPLETED]
  5. Implement `reports.ReportEvidence` and `reports.Dispute`. [COMPLETED]
  6. Implement `verification.VerificationRequest` and `verification.VerificationResult`.
- **Deliverables**: Schema migrations, updated model definitions across apps.
- **Dependencies**: Phase 2.
- **Testing**: Django ORM creation/deletion unit tests and relationship cascades.
- **Status**: **IN PROGRESS**

---

### Phase 4 — Authentication, Roles, and Permissions (RBAC)
- **Objective**: Implement granular User roles and access control boundaries.
- **Major Tasks**:
  1. Enhance `users.User` model with explicit Role choices (`Individual`, `Employer`, `Business`, `Moderator`, `Verification Officer`, `Authorized Agency`).
  2. Implement role-checking helpers and object-level permission validators.
  3. Configure Django Admin registrations across all app `admin.py` files.
- **Deliverables**: Custom User RBAC logic, permission helper utilities, configured Admin site.
- **Dependencies**: Phase 3.
- **Testing**: Unit tests asserting permission denials for unauthorized roles attempting restricted actions.
- **Security Considerations**: Ensure non-admin roles cannot access management features or unauthorized data.

---

### Phase 5 — Security, Privacy, and Audit Architecture
- **Objective**: Build foundational security controls, automated audit logs, and evidence access protection.
- **Major Tasks**:
  1. Implement automated `core.AuditLog` signals for tracking model state transitions.
  2. Build pre-signed URL access controls for `ReportEvidence` files.
  3. Enforce peppered HMAC hashing helpers for identifier lookups.
  4. Implement data retention and NDPR right-to-erasure workflows.
- **Deliverables**: `AuditLog` signal handlers, security middleware, privacy utilities.
- **Dependencies**: Phase 4.
- **Testing**: Penetration unit tests simulating illegal access attempts to private evidence files.
- **Security Considerations**: Ensure evidence files are stored in private object buckets and never publicly readable.

---

### Phase 6 — Redis Caching & Background Jobs Evaluation
- **Objective**: Connect local Redis (`redis://localhost:6379/0`) for rate-limiting search queries, and evaluate/implement Celery only if async jobs are required.
- **Major Tasks**:
  1. Configure `settings.py` to use local Redis for cache / rate-limiting.
  2. Implement Redis rate-limiting decorators for public CHECK endpoints.
  3. Evaluate Celery requirement for background notifications / PDF rendering.
- **Deliverables**: Redis cache integration, search rate-limiter, optional Celery broker config.
- **Dependencies**: Phase 5.
- **Testing**: `redis-cli ping` integration tests, rate-limit response verification (`429 Too Many Requests`).

---

### Phase 7 — Core VerifyNG Application & API Features
- **Objective**: Complete end-to-end CHECK lookup and REPORT submission workflows across Ninja API and Web templates.
- **Major Tasks**:
  1. Implement Ninja API endpoints (`GET /api/v1/check/{identifier_hash}`, `POST /api/v1/reports/`).
  2. Complete `public_website` template views (`home.html`, `check.html`, `report.html`).
  3. Implement `dashboard` app views for authenticated user management.
- **Deliverables**: Fully functioning CHECK lookup, neutral REPORT workflow, and user dashboard.
- **Dependencies**: Phase 6.
- **Testing**: Live browser testing, Django Ninja API interactive docs (`/api/v1/docs`).

---

### Phase 8 — Verification Workflows & Document Generation Engine
- **Objective**: Build the worker verification workflow and "VerifyNG Verification Report" PDF generator.
- **Major Tasks**:
  1. Implement `verification` app workflows for requesting employment/identity verifications.
  2. Create PDF report generator for VerifyNG Verification Reports.
  3. Add clear legal disclaimers explicitly distinguishing VerifyNG reports from UK DBS certificates.
- **Deliverables**: Verification request engine, PDF report generator module.
- **Dependencies**: Phase 7.
- **Testing**: PDF generation tests, visual template inspection, access permission checks on PDF downloads.

---

### Phase 9 — Full Test Suite & Quality Assurance
- **Objective**: Execute comprehensive automated unit, integration, and security tests.
- **Major Tasks**:
  1. Write and execute complete Django test suite (`python manage.py test`).
  2. Verify 100% pass rate across `users`, `identities`, `reports`, `verification`, `api`, `public_website`.
  3. Perform manual mobile & desktop browser QA on mobile and desktop viewports.
- **Deliverables**: Green test report, QA bugfix log.
- **Dependencies**: Phase 8.
- **Testing**: Automated `manage.py test` execution, cross-browser manual check.

---

### Phase 10 — Production Readiness & Deployment Hardening
- **Objective**: Final environment validation, security hardening, and documentation wrap-up.
- **Major Tasks**:
  1. Verify `DEBUG=False` handling, secure headers, CSRF flags.
  2. Final audit of `.env` configuration template.
  3. Complete user documentation and deployment guide.
- **Deliverables**: Production-ready codebase, deployment documentation.
- **Dependencies**: Phase 9.
- **Testing**: Django security deployment check (`python manage.py check --deploy`).

---

## F. Comprehensive Progress Checklist

### Phase 1 — Project Inspection & Restructuring
- [x] Inspect original project structure
- [x] Remove obsolete `docker-compose.yml`
- [x] Move app folders out of `backend/` to project root
- [x] Rename `accounts` → `users`
- [x] Rename `public_site` → `public_website`
- [x] Create app stubs for `dashboard`, `verification`, `core`
- [x] Create Master Development Plan document (`docs/VERIFYNG_DEVELOPMENT_PLAN.md`)

### Phase 2 — PostgreSQL 18 & Database Foundation
- [x] Create `.env.example` template
- [x] Create local `.env` with local PostgreSQL 18 credentials
- [x] Update `config/settings.py` (`INSTALLED_APPS`, `AUTH_USER_MODEL`, `DATABASES`, `BASE_DIR`)
- [x] Update app configs (`users/apps.py`, `public_website/apps.py`)
- [x] Update import statements across apps (`users`, `identities`, `reports`, `api`, `config`)
- [x] Create security `.gitignore` protecting secrets
- [x] Run `python manage.py check` to verify configuration
- [x] Run `python manage.py migrate` to create tables in local PostgreSQL 18

### Phase 3 — Database & Domain Model Architecture
- [x] Refine `SubjectEntity` model (`person` / `business`)
- [x] Refine `Identifier` model with database indexing
- [x] Add `BusinessProfile` model & Django Admin registration
- [x] Refine `FraudReport` neutral moderation lifecycle states
- [x] Add `ReportEvidence` model & `Dispute` model
- [ ] Add `VerificationRequest` & `VerificationResult` models
- [ ] Run migrations for domain models

### Phase 4 — Authentication & User Roles (RBAC)
- [ ] Add Role choices to `users.User` (`Individual`, `Employer`, `Business`, `Moderator`, `Officer`, `Agency`)
- [ ] Build object-level permission helper utilities
- [ ] Register all models in their respective `admin.py` files

### Phase 5 — Security, Privacy & Audit Architecture
- [ ] Build automated `AuditLog` signals for state transitions
- [ ] Implement pre-signed URL access controls for `ReportEvidence`
- [ ] Implement data retention and NDPR deletion helpers

### Phase 6 — Redis Caching & Background Jobs
- [ ] Configure local Redis (`redis://localhost:6379/0`) in `settings.py`
- [ ] Add Redis rate-limiting decorators to public CHECK endpoints
- [ ] Evaluate and configure Celery if background tasks are required

### Phase 7 — Core Application & API Features
- [ ] Implement Ninja API endpoints (`/api/v1/check/{identifier_hash}`, `/api/v1/reports/`)
- [ ] Finalize `public_website` template views and navigation
- [ ] Implement authenticated `dashboard` views

### Phase 8 — Verification Workflows & Document Engine
- [ ] Build `verification` app background check request flow
- [ ] Build VerifyNG Verification Report PDF generator
- [ ] Add legal disclaimers distinguishing reports from UK DBS certificates

### Phase 9 — Full Test Suite & Quality Assurance
- [ ] Write unit tests for all apps
- [ ] Run `python manage.py test` and achieve 100% pass rate
- [ ] Perform manual mobile & desktop browser QA

### Phase 10 — Production Hardening
- [ ] Run `python manage.py check --deploy`
- [ ] Validate production `.env` setup
- [ ] Finalize project documentation

---

## G. Testing Approach & Verification Standards

1. **Automated Unit & Integration Tests**: Executed locally via `python manage.py test`. Tests cover models, API routes, permissions, and moderation state transitions.
2. **Local Django Execution**: Running `python manage.py runserver` to serve the application locally on `http://127.0.0.1:8000/`.
3. **Live Browser Inspection**: Manually opening pages in Chrome/Firefox/Edge to verify responsive layout, Bootstrap 5 UI components, Alpine.js interactivity, dynamic forms, and template rendering.
4. **API Testing**: Interacting directly with Django Ninja endpoints via curl, PowerShell `Invoke-RestMethod`, or the interactive OpenAPI documentation at `http://127.0.0.1:8000/api/v1/docs`.
5. **Database Inspection**: Using `pgAdmin 4` or `psql` to directly inspect table structures, applied migrations, and data integrity in local PostgreSQL 18.
