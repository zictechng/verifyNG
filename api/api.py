import json
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError
from django.http import HttpResponse, Http404
from identities.utils import hash_identifier_value
from identities.services import lookup_public_record
from core.rate_limiting import check_rate_limit

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


class ReportSchema(Schema):
    target_hash: str
    allegation: str


@api.post("/reports/")
def create_report(request, payload: ReportSchema):
    # Mock implementation
    return {"status": "submitted"}

