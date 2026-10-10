# VerifyNG — Development Standards & Governance

> Nigeria's First Public Trust & Safety Platform  
> "Check before you trust. Report when you are wronged. Verify before you hire."

---

## 1. Project Overview

VerifyNG is a security-sensitive Nigerian public trust and fraud-check platform that lets any
Nigerian:

- **CHECK** — Search a phone number, name, NIN, or bank account and receive a Trust Summary
  built from verified data in under 60 seconds.
- **REPORT** — Submit a verified, permanent fraud report so others are warned.
- **VERIFY** — Workers build a portable digital trust profile; employers and landlords check it
  before committing.

The **primary product requirements document** is `docs/VerifyNG_Business_Plan.docx`.  
All architectural and implementation decisions must be cross-referenced against it.  
Where the plan contains unnecessary complexity, conflicts, insecure approaches, or outdated
assumptions, identify the issue explicitly and propose a better solution **before** implementing
anything.

---

## 2. Target Technology Stack

These technologies are the intended stack. They are **not automatically mandatory** — each must
be justified against the business requirement it serves.

| Layer | Technology |
|---|---|
| Language | Python 3.12.x (project venv must use 3.12.x) |
| Core web framework | Django 5.x |
| API / webhook layer | FastAPI |
| Database | PostgreSQL 16 |
| Cache / broker | Redis 7 |
| Task queue | Celery |
| Frontend framework | Bootstrap 5 |
| Frontend interactivity | Alpine.js |
| Rendering strategy | Server-rendered HTML / Django templates |
| Containerisation | Docker / Docker Compose |
| WSGI server | Gunicorn |
| ASGI server | Uvicorn |
| Payment gateway | Paystack |
| Messaging | WhatsApp Business API (Meta Cloud API) |
| Identity verification | Licensed NIN / BVN providers (e.g. Smile Identity, Prembly, Mono) |
| Certificate verification | WAEC DigiCert, NECO e-Verify, NYSC Portal |
| SMS fallback | Africa's Talking SMS API |
| Email | Django Email + SendGrid |
| File / object storage | AWS S3 (or compatible) |

---

## 3. Phased Development Plan

Phases must be completed in order. Do **not** skip phases.  
Do **not** implement multiple major phases simultaneously unless explicitly instructed.

| Phase | Name |
|---|---|
| 0 | Requirements and architecture analysis |
| 1 | Development foundation |
| 2 | Authentication and authorization |
| 3 | User identity and profiles |
| 4 | Business verification |
| 5 | Fraud / scam reporting |
| 6 | Employment / person verification |
| 7 | Verification reports and documents |
| 8 | Employer portal |
| 9 | Security / agency portal |
| 10 | Administration and moderation |
| 11 | Notifications |
| 12 | Payments and subscriptions |
| 13 | Security, privacy and compliance hardening |
| 14 | Comprehensive testing |
| 15 | Deployment |
| 16 | Production hardening |

---

## 4. Mandatory Phase Workflow

Every phase must follow this gate process in full:

```
PLAN → REVIEW → APPROVAL → IMPLEMENT → TEST → SECURITY REVIEW → FIX → ACCEPTANCE → NEXT PHASE
```

### Pre-implementation checklist (stop and document all of these before writing code)

1. What will be changed and why.
2. Files that will be created or modified.
3. Database changes (new tables, columns, indexes, constraints, migrations).
4. New dependencies (Python packages, external services, APIs).
5. APIs introduced or consumed.
6. Frontend / template changes.
7. Security implications.
8. Tests to be written.
9. Acceptance criteria for this phase.

**STOP and wait for explicit approval** whenever the phase requires an architectural or
implementation decision.  Do not begin implementation until approval is confirmed.

---

## 5. Code Organisation

Maintain strict separation of concerns at all times.

```
verifyNG/
├── config/                  # Django settings (base, dev, prod), WSGI/ASGI
├── apps/
│   ├── accounts/            # User model, authentication, permissions
│   ├── identity/            # NIN / BVN verification, identity profiles
│   ├── reports/             # Fraud reports, disputes, evidence
│   ├── verify_profiles/     # Worker / individual trust profiles
│   ├── employer/            # Employer portal, bulk checks
│   ├── agency/              # Security / agency portal
│   ├── notifications/       # WhatsApp, SMS, email dispatch
│   ├── payments/            # Paystack integration, subscriptions
│   ├── certificates/        # WAEC / NECO / NYSC certificate verification
│   ├── audit/               # Audit logging, access logs
│   └── moderation/          # Admin moderation tools
├── api/                     # FastAPI application (mounted alongside Django)
│   ├── webhooks/            # WhatsApp Business API webhook handlers
│   ├── checks/              # Real-time check API endpoints
│   └── integrations/        # Third-party async API calls (NIN/BVN/WAEC)
├── templates/               # Django HTML templates only — no inline CSS or JS
├── static/
│   ├── css/                 # All CSS here — never inline in templates
│   ├── js/                  # All JavaScript here — never inline in templates
│   └── images/
├── tests/                   # Mirrors apps/ structure
├── docs/                    # Business plan, architecture documents
├── docker/                  # Dockerfiles, docker-compose files
├── scripts/                 # Dev utility scripts
└── CLAUDE.md
```

### Separation rules

- HTML / templates remain in `templates/` — no large inline CSS or JS blocks.
- CSS remains in `static/css/` — one file per component / feature area.
- JavaScript remains in `static/js/` — one file per component / feature area.
- Backend code is modular. No single file combines unrelated functionality.
- Keep clear boundaries between: configuration, models, schemas, repositories, services,
  API routes, authentication, permissions, background tasks, utilities, templates, static
  assets, and tests.

---

## 6. Security Requirements

VerifyNG processes identity data, employment records, fraud allegations, evidence, and
potentially reputation-affecting information.  Security is foundational — not an afterthought.

### Data classification

The system must always distinguish clearly between:

| Status | Meaning |
|---|---|
| `allegation` | Submitted claim — not yet reviewed |
| `submitted` | Report received and queued |
| `evidence_submitted` | Evidence uploaded and awaiting review |
| `under_review` | Active moderation in progress |
| `verified` | Confirmed by VerifyNG review process |
| `rejected` | Report rejected after review |
| `disputed` | Reported person has contested the report |
| `resolved` | Dispute resolved |

**Never treat an unverified allegation as an established fact.**

### Mandatory controls

- Authentication & authorisation on every protected route.
- Role-based permissions (user, employer, agent, moderator, admin, security-agency).
- Rate limiting: anonymous checks ≤ 3 per IP/hour; authenticated users ≤ 50/day.
- Input validation on all forms and API endpoints.
- CSRF protection (Django defaults + explicit verification on API boundaries).
- NIN and BVN stored **only** as irreversible SHA-256 hashes — never in plain text.
- Secure file uploads with malware scanning before storage.
- Evidence stored in private S3 bucket; access only via pre-signed URLs.
- Audit logging: every check, report, update, admin action, and access event logged with
  timestamp, user ID, and IP address — immutable.
- Secrets management via environment variables / secrets manager — never hardcoded.
- Privacy controls and data minimisation.
- Abuse prevention and fraud-detection on the report submission flow.
- Two-factor authentication for employer and high-verification-level accounts.
- HTTPS enforcement, secure cookies, clickjacking prevention (Django security defaults).
- Anonymous fraud reports are **not accepted** — reporter must verify NIN or BVN first.

---

## 7. Document and Certificate Terminology

VerifyNG-generated documents must **not** be represented as government-issued DBS certificates
or Police Clearance Certificates unless there is explicit legal authorisation.

Use accurate terminology:

- **VerifyNG Verification Report**
- **VerifyNG Verification Certificate**

Every issued document must include:

| Field | Description |
|---|---|
| Document ID | Unique, non-sequential identifier |
| Verification date | ISO 8601 date |
| Verification type | CHECK / VERIFY / CERTIFICATE |
| Source information | Data sources consulted |
| Verification status | One of the statuses defined in §6 |
| Issuer | VerifyNG (with company registration number) |
| QR code | Links to real-time verification URL |
| Verification URL | Publicly accessible status check |
| Expiry / revocation state | Validity period and revocation flag |
| Disclaimer | "This document is a VerifyNG Verification Report and is not a government-issued certificate." |

---

## 8. Legal and Compliance Flags

The following areas **require professional legal and compliance review** before implementation.
Do not make legal assumptions. Flag these explicitly in each relevant phase plan.

- Nigerian Data Protection Regulation (NDPR) obligations
- NIMC Act — NIN data handling and licensing requirements
- CBN Regulations — BVN verification provider requirements
- Employment background check regulations
- Defamation and reputation risk — publishing fraud reports
- Right of response — reported person's rights
- Dispute resolution and correction mechanisms
- Data retention and deletion policies
- Security-agency access to records
- Certificate verification legal basis
- FCCPC consumer-protection registration
- Payment processing (Paystack) and financial services regulations
- Evidence handling — uploaded documents containing sensitive personal data

---

## 9. Database Standards

Database architecture must be reviewed and approved before any migration is created.

### Every model must include

```python
created_at    = models.DateTimeField(auto_now_add=True)
updated_at    = models.DateTimeField(auto_now=True)
is_active     = models.BooleanField(default=True)
```

### Design considerations for every phase

- Relationships and foreign keys
- Unique constraints
- Indexes (especially on phone, NIN hash, BVN hash, status fields)
- Status transition validation (use a state machine pattern)
- Soft deletion where appropriate (`is_active` flag)
- Audit fields on all sensitive records
- Data retention and scheduled deletion
- Dispute relationships
- Evidence relationships
- Verification relationships

### Do not create migrations until the database architecture for the relevant phase has been
reviewed and approved.

---

## 10. Django + FastAPI Integration

Django handles the full web application (HTML rendering, user authentication, admin, ORM,
Celery task dispatch).

FastAPI runs as a separate ASGI application mounted alongside Django, handling only:

- WhatsApp Business API webhooks (must respond within 20 seconds)
- Real-time check queries (sub-100 ms target)
- Async third-party API calls (NIN / BVN / WAEC — non-blocking)

They share: PostgreSQL, Redis, and S3.

Nginx routes:
- `/api/v1/*` → FastAPI (Uvicorn)
- Everything else → Django (Gunicorn)

FastAPI must call Django ORM models directly via the shared database.  For complex business
logic, FastAPI calls Django's internal API rather than duplicating logic.

---

## 11. Testing Requirements

A feature is **complete only when its acceptance criteria are met and relevant tests pass**.
Writing code is not the same as completing a feature.

Every implemented feature must have:

- Unit tests
- Integration tests
- API tests
- Authentication and permission tests
- Input validation tests
- Security tests (including rate limiting, CSRF, auth bypass attempts)
- File upload tests (including malicious file rejection)
- Workflow and status-transition tests
- WhatsApp webhook handler tests (mock Meta Cloud API)

Tests mirror the `apps/` directory structure under `tests/`.

---

## 12. Git Workflow

- Inspect Git status before major implementation work.
- Make changes in small, logical increments with descriptive commit messages.
- Run tests after every meaningful change.
- Do **not** use destructive Git commands (reset --hard, force push, branch -D) without
  explicit approval.
- Do **not** delete or overwrite existing user work without explicit approval.

---

## 13. Current Project State

**Phase 0 — Requirements and architecture analysis** (not yet started)

The only files currently in the project are:

```
docs/
  VerifyNG_Business_Plan.docx    # Primary requirements document
  bp_extract.txt                 # Plain-text extract of business plan
CLAUDE.md                        # This file
```

No application code, virtual environment, database, migrations, or infrastructure exists.

Do **not** begin implementation of any phase without explicit approval.

---

## 14. Recommended Next Step

Read and analyse `docs/VerifyNG_Business_Plan.docx` (or `docs/bp_extract.txt`) in full as
**Phase 0** work, then produce:

1. A structured requirements analysis.
2. A critical architectural review (identifying any issues with the proposed stack or design).
3. A proposed database schema overview for Phase 1.
4. A list of compliance flags requiring legal review.
5. A Phase 1 implementation plan following the gate process in §4.

**Wait for explicit approval of the Phase 1 plan before writing any code.**
