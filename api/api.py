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

logger = logging.getLogger(__name__)

api = NinjaAPI()


class CheckResponse(Schema):
    # Preserved existing fields (backward compatibility with Phase 6 test suite)
    subject_name: str
    entity_type: str
    active_reports_count: int

    # Status separation and public safety additions (Phase 7, Batch 7.1)
    is_verified: bool
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


@api.post("/reports/")
def create_report(request, payload: ReportSchema):
    # Mock implementation
    return {"status": "submitted"}

