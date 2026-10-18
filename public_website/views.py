# public_website/views.py
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render

from core.rate_limiting import check_rate_limit, get_client_ip
from reports.forms import FraudReportSubmissionForm
from reports.services import create_fraud_report
from reports.storage_services import StorageError
from verification.forms import VerificationRequestCreateForm
from verification.services import create_verification_request

logger = logging.getLogger(__name__)


def home(request):
    return render(request, 'public/home.html')


def check(request):
    is_limited, retry_after = check_rate_limit(request, namespace="web_check")
    if is_limited:
        response = HttpResponse(
            "Rate limit exceeded. Please wait before retrying.",
            status=429,
            content_type="text/plain; charset=utf-8"
        )
        response['Retry-After'] = str(retry_after)
        return response

    return render(request, 'public/check.html')



def privacy_legal(request, tab=None):
    """
    Dual-tab Privacy Policy and Legal/Terms view with instant mobile tab switching.
    """
    active_tab = tab or request.GET.get('tab', 'privacy')
    if active_tab not in ('privacy', 'legal'):
        active_tab = 'privacy'
    return render(request, 'public/privacy_legal.html', {'active_tab': active_tab})


@login_required
def report(request):
    """
    GET  — render blank FraudReportSubmissionForm.
    POST — validate, delegate to create_fraud_report(), redirect on success.

    Authentication: @login_required — anonymous reports are rejected (CLAUDE.md §6).
    Error handling:
      StorageError  → evidence upload failed; surface as a field-level form error.
      ValidationError → service-level business rule violation; surface as non-field error.
      Exception     → unexpected; log and surface as non-field error.
    """
    if request.method == 'POST':
        form = FraudReportSubmissionForm(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                fraud_report = create_fraud_report(
                    reporter=request.user,
                    subject_name=cd['subject_name'],
                    subject_type=cd['subject_type'],
                    title=cd['title'],
                    allegation=cd['allegation'],
                    incident_date=cd.get('incident_date'),
                    evidence_file=cd.get('evidence_file'),
                    evidence_type=cd.get('evidence_type'),
                    evidence_description=cd.get('evidence_description', ''),
                    suspect_phone=cd.get('suspect_phone'),
                    suspect_bank_account=cd.get('suspect_bank_account'),
                    suspect_bank_name=cd.get('suspect_bank_name'),
                    suspect_cac_number=cd.get('suspect_cac_number'),
                    suspect_email=cd.get('suspect_email'),
                    suspect_location=cd.get('suspect_location'),
                    suspect_state=cd.get('suspect_state'),
                    suspect_city=cd.get('suspect_city'),
                )
                messages.success(
                    request,
                    f"Your report has been submitted. Reference: {fraud_report.reference_number}"
                )
                return redirect('reports:detail', pk=fraud_report.pk)

            except StorageError as e:
                logger.warning("Evidence upload failed for user %s: %s", request.user.id, e)
                form.add_error(
                    'evidence_file',
                    "Evidence upload failed. Please try again or submit without a file."
                )
            except ValidationError as e:
                logger.warning("ValidationError in report submission for user %s: %s", request.user.id, e)
                form.add_error(None, e.message if hasattr(e, 'message') else str(e))
            except Exception as e:
                logger.exception("Unexpected error in report submission for user %s", request.user.id)
                form.add_error(None, "An unexpected error occurred. Please try again.")
    else:
        form = FraudReportSubmissionForm()

    return render(request, 'public/report.html', {'form': form})


@login_required
def verify(request):
    """
    GET  — render blank VerificationRequestCreateForm.
    POST — validate, delegate to create_verification_request(), redirect on success.

    Authentication: @login_required — unauthenticated users cannot submit verification requests.
    The requester's IP address is captured for audit logging.
    Error handling:
      ValidationError → service-level business rule; surfaced as non-field error.
      Exception       → unexpected; logged and surfaced as non-field error.
    """
    if request.method == 'POST':
        form = VerificationRequestCreateForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                verification_request = create_verification_request(
                    requester=request.user,
                    subject_name=cd['subject_name'],
                    subject_type=cd['subject_type'],
                    verification_type=cd['verification_type'],
                    notes=cd.get('notes', ''),
                    identifier_type=cd.get('identifier_type') or None,
                    identifier_value=cd.get('identifier_value') or None,
                    ip_address=get_client_ip(request),
                )
                messages.success(
                    request,
                    f"Verification request submitted. Reference: {verification_request.reference_number}"
                )
                return redirect('verification:detail', pk=verification_request.pk)

            except ValidationError as e:
                logger.warning(
                    "ValidationError in verification submission for user %s: %s",
                    request.user.id, e
                )
                form.add_error(None, e.message if hasattr(e, 'message') else str(e))
            except Exception as e:
                logger.exception(
                    "Unexpected error in verification submission for user %s", request.user.id
                )
                form.add_error(None, "An unexpected error occurred. Please try again.")
    else:
        form = VerificationRequestCreateForm()

    return render(request, 'public/verify.html', {'form': form})

