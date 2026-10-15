
# employer/tasks.py
"""
Celery tasks for the employer app.

process_bulk_upload_task:
    Reads each BulkCheckRow attached to a BulkCheckUpload, queries the
    identities/fraud layer for each candidate, writes results back, and
    updates the parent upload's progress counters.

    This task is deliberately kept simple and safe:
    - It never stores raw NIN — it only compares already-hashed values.
    - It processes rows one-by-one so a single bad row never kills the batch.
    - All DB writes use minimal update_fields to avoid clobbering concurrent
      changes.
"""

import hashlib
import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone
from django.utils import timezone
from datetime import timedelta
from employer.models import StaffCheckMonitor, StaffCheckRequest
from employer.models import BulkCheckUpload, BulkCheckRow
from identities.models import Identifier
from reports.models import FraudReport
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trust_lookup(phone_number: str, nin_hash: str) -> dict:
    """
    Look up a candidate in the VerifyNG identity + fraud layer.

    Returns a dict with keys:
        found (bool)        — whether a SubjectEntity was matched
        fraud_flags (int)   — count of active verified fraud reports
        trust_score (float) — 0.0–100.0, or None if no score exists
        summary (str)       — human-readable one-line result
    """
    from identities.models import Identifier, SubjectEntity
    try:
        # Match by phone first, then by NIN hash
        subject = None
        if phone_number:
            ident = (
                Identifier.objects
                .filter(identifier_type='phone', value=phone_number, is_active=True)
                .select_related('subject')
                .first()
            )
            if ident:
                subject = ident.subject

        if subject is None and nin_hash:
            ident = (
                Identifier.objects
                .filter(identifier_type='nin', value=nin_hash, is_active=True)
                .select_related('subject')
                .first()
            )
            if ident:
                subject = ident.subject

        if subject is None:
            return {
                'found': False,
                'fraud_flags': 0,
                'trust_score': None,
                'summary': 'No record found in VerifyNG database.',
            }

        # Count verified fraud reports
        fraud_count = 0
        try:
            from reports.models import FraudReport
            fraud_count = FraudReport.objects.filter(
                subject=subject,
                status='verified',
                is_active=True,
            ).count()
        except Exception:
            pass

        # Trust score
        score = None
        try:
            trust = subject.trust_scores.filter(is_active=True).order_by('-updated_at').first()
            if trust:
                score = float(trust.score)
        except Exception:
            pass

        summary = (
            f"Record found. Fraud flags: {fraud_count}. "
            f"Trust score: {score if score is not None else 'N/A'}."
        )
        return {
            'found': True,
            'fraud_flags': fraud_count,
            'trust_score': score,
            'summary': summary,
        }

    except Exception as exc:
        logger.exception("_trust_lookup error for phone=%s: %s", phone_number, exc)
        return {
            'found': False,
            'fraud_flags': 0,
            'trust_score': None,
            'summary': f'Lookup error: {exc}',
        }


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_bulk_upload_task(self, upload_id: str) -> dict:
    """
    Process every pending BulkCheckRow in the given BulkCheckUpload.

    Args:
        upload_id: str UUID of the BulkCheckUpload record.

    Returns:
        dict with keys: processed, failed, skipped, upload_id
    """
    try:
        upload = BulkCheckUpload.objects.get(id=upload_id)
    except BulkCheckUpload.DoesNotExist:
        logger.error("process_bulk_upload_task: upload %s not found", upload_id)
        return {'error': 'Upload not found', 'upload_id': upload_id}

    # Mark as processing
    upload.status = 'processing'
    upload.save(update_fields=['status', 'updated_at'])

    processed = 0
    failed = 0
    skipped = 0

    rows = BulkCheckRow.objects.filter(upload=upload, status='pending').order_by('row_number')

    for row in rows:
        # Skip rows with no usable identifier
        if not row.phone_number and not row.nin_hash:
            row.status = 'skipped'
            row.result_summary = 'Skipped — no phone number or NIN provided.'
            row.checked_at = timezone.now()
            row.save(update_fields=['status', 'result_summary', 'checked_at', 'updated_at'])
            skipped += 1
            continue

        row.status = 'checking'
        row.save(update_fields=['status', 'updated_at'])

        try:
            result = _trust_lookup(row.phone_number, row.nin_hash)

            row.status = 'completed'
            row.result_summary = result['summary']
            row.result_data = result
            row.checked_at = timezone.now()
            row.save(update_fields=[
                'status', 'result_summary', 'result_data', 'checked_at', 'updated_at',
            ])
            processed += 1

        except Exception as exc:
            logger.exception(
                "process_bulk_upload_task: row %s (upload %s) failed: %s",
                row.row_number, upload_id, exc,
            )
            row.status = 'failed'
            row.result_summary = f'Processing error: {exc}'
            row.checked_at = timezone.now()
            row.save(update_fields=['status', 'result_summary', 'checked_at', 'updated_at'])
            failed += 1

        finally:
            # Always update processed_count on the parent upload
            with transaction.atomic():
                BulkCheckUpload.objects.filter(id=upload_id).update(
                    processed_count=BulkCheckUpload.objects.filter(id=upload_id)
                    .values_list('processed_count', flat=True)[0] + 1,
                    updated_at=timezone.now(),
                )

    # Final status
    if failed > 0 and processed == 0 and skipped == 0:
        upload.status = 'failed'
        upload.error_summary = f'All {failed} rows failed during processing.'
    else:
        upload.status = 'completed'
        upload.error_summary = '' if failed == 0 else f'{failed} row(s) failed during processing.'

    upload.processed_count = processed + failed + skipped
    upload.save(update_fields=['status', 'processed_count', 'error_summary', 'updated_at'])

    logger.info(
        "process_bulk_upload_task DONE upload=%s processed=%d failed=%d skipped=%d",
        upload_id, processed, failed, skipped,
    )
    return {
        'upload_id': upload_id,
        'processed': processed,
        'failed': failed,
        'skipped': skipped,
    }



# ---------------------------------------------------------------------------
# Monitoring alert task (Batch 7)
# ---------------------------------------------------------------------------

def _get_current_fraud_flag_count(nin_hash: str, phone_number: str) -> int:
    """
    Return the current count of verified fraud reports matched to this subject.
    Matches by NIN hash first, then phone. Returns 0 if no subject found.
    """
    subject = None

    if nin_hash:
        ident = (
            Identifier.objects
            .filter(type='nin', value_hash=nin_hash)
            .select_related('subject')
            .first()
        )
        if ident:
            subject = ident.subject

    if subject is None and phone_number:
        ident = (
            Identifier.objects
            .filter(type='phone', value_hash=phone_number)
            .select_related('subject')
            .first()
        )
        if ident:
            subject = ident.subject

    if subject is None:
        return 0

    return FraudReport.objects.filter(
        target_subject=subject,
        state='verified',
        is_active=True,
    ).count()


def _send_monitor_alert_email(monitor, previous_flags: int, current_flags: int) -> None:
    """
    Send a branded HTML email alert to the employer contact when a monitored
    staff member's fraud flag count changes.
    """

    check = monitor.check_request
    employer = monitor.employer

    # Determine the employer contact email
    contact_email = employer.contact_email or (
        employer.owner.email if employer.owner else None
    )
    if not contact_email:
        logger.warning(
            "monitor_alert: no contact email for employer %s — skipping",
            employer.id,
        )
        return

    site_name = getattr(settings, 'SITE_NAME', 'VerifyNG')
    site_url  = getattr(settings, 'SITE_BASE_URL', 'https://verifyng.com')

    ctx = {
        # Email base context
        'site_name':     site_name,
        'site_url':      site_url,
        'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@verifyng.com'),
        'company_reg':   getattr(settings, 'COMPANY_REG', ''),
        'logo_url':      getattr(settings, 'EMAIL_LOGO_URL', ''),
        # Alert-specific context
        'company_name':    employer.company_name,
        'staff_name':      check.full_name,
        'previous_flags':  previous_flags,
        'current_flags':   current_flags,
        'flag_change':     current_flags - previous_flags,
        'flag_increased':  current_flags > previous_flags,
        'check_detail_url': f"{site_url}/employer/checks/{check.id}/",
        'monitoring_url':   f"{site_url}/employer/monitoring/",
    }

    subject_line = (
        f"⚠ Alert: Fraud flag change for {check.full_name} — {employer.company_name}"
        if current_flags > previous_flags
        else f"✓ Update: Fraud flags reduced for {check.full_name} — {employer.company_name}"
    )

    text_body = (
        f"Hello,\n\n"
        f"This is an automated VerifyNG monitoring alert for {employer.company_name}.\n\n"
        f"Staff member: {check.full_name}\n"
        f"Previous fraud flags: {previous_flags}\n"
        f"Current fraud flags:  {current_flags}\n\n"
        f"Please log in to review this change:\n{ctx['check_detail_url']}\n\n"
        f"To manage monitoring settings, visit:\n{ctx['monitoring_url']}\n\n"
        f"— {site_name} Team"
    )

    html_body = render_to_string('emails/monitor_alert.html', ctx)

    try:
        msg = EmailMultiAlternatives(
            subject=subject_line,
            body=text_body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', f'noreply@verifyng.com'),
            to=[contact_email],
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send(fail_silently=False)
        logger.info(
            "monitor_alert email sent: employer=%s staff=%s prev=%d cur=%d",
            employer.id, check.full_name, previous_flags, current_flags,
        )
    except Exception as exc:
        logger.exception(
            "monitor_alert email FAILED: employer=%s staff=%s: %s",
            employer.id, check.full_name, exc,
        )


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def run_monitor_checks_task(self) -> dict:
    """
    Periodic task: re-checks every active StaffCheckMonitor for fraud flag changes.

    For each active monitor:
      1. Get the current fraud flag count for the subject.
      2. If it differs from the stored count on StaffCheckRequest, update and send alert.
      3. Update last_checked / next_check timestamps.

    Should be scheduled to run nightly (e.g. 02:00 UTC via Celery Beat).
    """

    now = timezone.now()
    alerted = 0
    unchanged = 0
    errors = 0

    monitors = (
        StaffCheckMonitor.objects
        .filter(monitor_status='active', is_active=True, alert_on_change=True)
        .select_related('check_request', 'employer', 'employer__owner')
    )

    for monitor in monitors:
        check = monitor.check_request
        try:
            current_flags = _get_current_fraud_flag_count(
                nin_hash=check.nin_hash,
                phone_number=check.phone_number,
            )
            previous_flags = check.fraud_flags

            if current_flags != previous_flags:
                # Update stored count on check record
                StaffCheckRequest.objects.filter(id=check.id).update(
                    fraud_flags=current_flags,
                    updated_at=now,
                )
                # Send alert email (non-fatal)
                try:
                    _send_monitor_alert_email(monitor, previous_flags, current_flags)
                except Exception as email_exc:
                    logger.exception(
                        "run_monitor_checks_task: alert email failed for monitor %s: %s",
                        monitor.id, email_exc,
                    )
                alerted += 1
            else:
                unchanged += 1

            # Update timestamps
            StaffCheckMonitor.objects.filter(id=monitor.id).update(
                last_checked=now,
                next_check=now + timedelta(hours=24),
                updated_at=now,
            )

        except Exception as exc:
            logger.exception(
                "run_monitor_checks_task: error on monitor %s: %s", monitor.id, exc,
            )
            errors += 1

    logger.info(
        "run_monitor_checks_task DONE: alerted=%d unchanged=%d errors=%d",
        alerted, unchanged, errors,
    )
    return {'alerted': alerted, 'unchanged': unchanged, 'errors': errors}


