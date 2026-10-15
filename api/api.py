import json
import logging
from typing import Optional
from datetime import date

from ninja import NinjaAPI, Schema
from ninja.errors import HttpError
from ninja.security import django_auth
from django.core.exceptions import ValidationError
from django.http import HttpResponse, Http404

from identities.utils import hash_identifier_value
from identities.services import lookup_public_record
from core.rate_limiting import check_rate_limit, get_client_ip
from reports.services import create_fraud_report
from reports.storage_services import StorageError
from verification.services import create_verification_request

logger = logging.getLogger(__name__)

api = NinjaAPI(urls_namespace='verifyng_api')

# WhatsApp Business API webhook router
from api.webhooks import router as whatsapp_router
api.add_router("/webhooks/", whatsapp_router)

class CheckResponse(Schema):
    # Preserved existing fields (backward compatibility with Phase 6 test suite)
    subject_name: str
    entity_type: str
    active_reports_count: int

    # Status separation and public safety additions (Phase 7, Batch 7.1)
    identity_verified: bool
    verification_label: str
    has_active_flags: bool
    published_reports_count: int
    disputed_reports_count: int
    official_business_name: str | None = None
    allegation_notice: str
    trust_score:        int | None = None
    trust_label:        str = 'Unknown'
    trust_label_colour: str = 'secondary'
    identity_verified:  bool = False


class CheckLookupRequest(Schema):
    identifier_type: str
    identifier_value: str


# Static route MUST be registered before parameterized route /check/{identifier_hash}
@api.post("/check/lookup", response=CheckResponse)
def check_lookup(request, payload: CheckLookupRequest):
    is_limited, retry_after = check_rate_limit(request, namespace="api_check")
    if is_limited:
        response = HttpResponse(
            json.dumps({"detail": "Rate limit exceeded. Please wait before retrying."}),
            status=429,
            content_type="application/json"
        )
        response['Retry-After'] = str(retry_after)
        return response

    try:
        val_hash = hash_identifier_value(payload.identifier_type, payload.identifier_value)
    except ValueError as e:
        raise HttpError(400, str(e))

    record = lookup_public_record(val_hash)
    if not record:
        raise Http404("No record found for this identifier.")

    return record


@api.get("/check/{identifier_hash}", response=CheckResponse)
def check_identifier(request, identifier_hash: str):
    is_limited, retry_after = check_rate_limit(request, namespace="api_check")
    if is_limited:
        response = HttpResponse(
            json.dumps({"detail": "Rate limit exceeded. Please wait before retrying."}),
            status=429,
            content_type="application/json"
        )
        response['Retry-After'] = str(retry_after)
        return response

    record = lookup_public_record(identifier_hash)
    if not record:
        raise Http404("No record found for this identifier hash.")

    return record


class ReportSubmitRequest(Schema):
    """
    Request body for POST /api/v1/reports/

    File upload (evidence) is NOT supported at the JSON API layer —
    evidence must be submitted via the web form (multipart/form-data).
    All fields mirror create_fraud_report() in reports/services.py.
    """
    # Required
    subject_name: str
    subject_type: str
    title: str
    allegation: str

    # Optional suspect identifiers
    suspect_phone: Optional[str] = None
    suspect_email: Optional[str] = None
    suspect_bank_account: Optional[str] = None
    suspect_bank_name: Optional[str] = None
    suspect_cac_number: Optional[str] = None

    # Optional location fields
    incident_date: Optional[date] = None
    suspect_location: Optional[str] = None
    suspect_state: Optional[str] = None
    suspect_city: Optional[str] = None


class ReportSubmitResponse(Schema):
    """Structured response returned after a successful report submission."""
    reference_number: str
    status: str
    subject_name: str
    message: str


@api.post(
    "/reports/",
    auth=django_auth,
    response={201: ReportSubmitResponse},
    summary="Submit a fraud / scam report",
    description=(
        "Authenticated endpoint. Anonymous submissions are not accepted. "
        "Evidence file upload must be done via the web form — this endpoint "
        "accepts JSON only and does not process file attachments."
    ),
)
def create_report(request, payload: ReportSubmitRequest):
    """
    POST /api/v1/reports/

    Wire: payload → create_fraud_report() → ReportSubmitResponse (201)

    Auth:  django_auth — requires an active Django session.
           Returns 401 automatically for unauthenticated callers via Ninja.

    Errors:
      400 — ValidationError raised by the service layer.
      500 — StorageError (guarded; file upload not applicable at API layer).
      500 — Unexpected exception.
    """
    try:
        fraud_report = create_fraud_report(
            reporter=request.user,
            subject_name=payload.subject_name,
            subject_type=payload.subject_type,
            title=payload.title,
            allegation=payload.allegation,
            incident_date=payload.incident_date,
            evidence_file=None,           # file upload not supported at API layer
            evidence_type=None,
            evidence_description="",
            suspect_phone=payload.suspect_phone,
            suspect_bank_account=payload.suspect_bank_account,
            suspect_bank_name=payload.suspect_bank_name,
            suspect_cac_number=payload.suspect_cac_number,
            suspect_email=payload.suspect_email,
            suspect_location=payload.suspect_location,
            suspect_state=payload.suspect_state,
            suspect_city=payload.suspect_city,
        )
    except ValidationError as exc:
        message = exc.message if hasattr(exc, "message") else str(exc)
        logger.warning(
            "ValidationError in API report submission for user %s: %s",
            request.user.pk, message,
        )
        raise HttpError(400, message)
    except StorageError as exc:
        logger.error(
            "StorageError in API report submission for user %s: %s",
            request.user.pk, exc,
        )
        raise HttpError(500, "Evidence storage failed. Please try again.")
    except Exception:
        logger.exception(
            "Unexpected error in API report submission for user %s",
            request.user.pk,
        )
        raise HttpError(500, "An unexpected error occurred. Please try again.")

    return 201, ReportSubmitResponse(
        reference_number=fraud_report.reference_number,
        status=fraud_report.status,
        subject_name=fraud_report.subject.name,
        message=(
            f"Report submitted successfully. "
            f"Reference number: {fraud_report.reference_number}. "
            "A VerifyNG moderator will review your report."
        ),
    )


class VerificationSubmitRequest(Schema):
    """
    Request body for POST /api/v1/verification/

    Mirrors create_verification_request() in verification/services.py.
    All fields are text only — no file upload at the API layer.
    """
    # Required
    subject_name: str
    subject_type: str
    verification_type: str

    # Optional identifier — both must be provided together or neither
    identifier_type: Optional[str] = None
    identifier_value: Optional[str] = None

    # Optional notes
    notes: Optional[str] = None


class VerificationSubmitResponse(Schema):
    """Structured response returned after a successful verification request submission."""
    reference_number: str
    status: str
    subject_name: str
    message: str


@api.post(
    "/verification/",
    auth=django_auth,
    response={201: VerificationSubmitResponse},
    summary="Submit a verification request",
    description=(
        "Authenticated endpoint. Anonymous submissions are not accepted. "
        "Provide identifier_type and identifier_value together or omit both. "
        "The requester's IP address is captured for audit logging."
    ),
)
def create_verification(request, payload: VerificationSubmitRequest):
    """
    POST /api/v1/verification/

    Wire: payload → create_verification_request() → VerificationSubmitResponse (201)

    Auth:  django_auth — requires an active Django session.
           Returns 401 automatically for unauthenticated callers via Ninja.

    Errors:
      400 — ValidationError raised by the service layer (invalid type,
             mismatched identifier pair, unsupported identifier type, etc.).
      500 — Unexpected exception.
    """
    try:
        verification_request = create_verification_request(
            requester=request.user,
            subject_name=payload.subject_name,
            subject_type=payload.subject_type,
            verification_type=payload.verification_type,
            notes=payload.notes or "",
            identifier_type=payload.identifier_type or None,
            identifier_value=payload.identifier_value or None,
            ip_address=get_client_ip(request),
        )
    except ValidationError as exc:
        message = exc.message if hasattr(exc, "message") else str(exc)
        logger.warning(
            "ValidationError in API verification submission for user %s: %s",
            request.user.pk, message,
        )
        raise HttpError(400, message)
    except Exception:
        logger.exception(
            "Unexpected error in API verification submission for user %s",
            request.user.pk,
        )
        raise HttpError(500, "An unexpected error occurred. Please try again.")

    return 201, VerificationSubmitResponse(
        reference_number=verification_request.reference_number,
        status=verification_request.status,
        subject_name=verification_request.target_subject.name,
        message=(
            f"Verification request submitted successfully. "
            f"Reference number: {verification_request.reference_number}. "
            "A VerifyNG officer will review your request within 2–5 business days."
        ),
    )
