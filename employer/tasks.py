
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
    from employer.models import BulkCheckUpload, BulkCheckRow

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

