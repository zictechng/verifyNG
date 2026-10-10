
import uuid
import json
import logging
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.core.exceptions import ValidationError

from verification.models import VerificationRequest, VerificationResult
from identities.models import SubjectEntity, Identifier
from identities.utils import normalize_identifier, hash_identifier_value, SUPPORTED_IDENTIFIER_TYPES
from reports.models import AuditLog
from core.tasks import send_email_notification_task

logger = logging.getLogger(__name__)


def generate_verification_reference_number() -> str:
    """Generates unique reference: VNG-VR-YYYYMMDD-XXXX"""
    today_str = timezone.now().strftime('%Y%m%d')
    unique_suffix = uuid.uuid4().hex[:4].upper()
    return f"VNG-VR-{today_str}-{unique_suffix}"


def create_verification_request(
    requester,
    subject_name: str,
    subject_type: str,
    verification_type: str,
    notes: str = "",
    identifier_type: str = None,
    identifier_value: str = None,
    ip_address: str = None
) -> VerificationRequest:
    """
    Submits a new VerificationRequest atomically.
    Resolves SubjectEntity using hashed identifier deduplication if provided;
    otherwise creates a new SubjectEntity.
    Dispatches Celery notification on transaction commit.
    """
    if subject_type not in dict(SubjectEntity.ENTITY_TYPES):
        raise ValidationError(f"Invalid subject type: {subject_type}")
    if verification_type not in dict(VerificationRequest.VERIFICATION_TYPES):
        raise ValidationError(f"Invalid verification type: {verification_type}")

    identifier_hash = None
    if identifier_type and identifier_value:
        if identifier_type not in SUPPORTED_IDENTIFIER_TYPES:
            raise ValidationError(f"Unsupported identifier type: {identifier_type}")
        try:
            identifier_hash = hash_identifier_value(identifier_type, identifier_value)
        except ValueError as e:
            raise ValidationError(str(e))

    max_retries = 3
    for attempt in range(max_retries):
        try:
            with transaction.atomic():
                target_subject = None
                if identifier_hash:
                    existing_id = Identifier.objects.select_related('subject').filter(
                        value_hash=identifier_hash
                    ).first()
                    if existing_id:
                        target_subject = existing_id.subject

                if not target_subject:
                    target_subject = SubjectEntity.objects.create(
                        name=subject_name.strip(),
                        type=subject_type
                    )
                    if identifier_hash:
                        Identifier.objects.create(
                            subject=target_subject,
                            type=identifier_type,
                            value_hash=identifier_hash
                        )

                ref_num = generate_verification_reference_number()
                verif_request = VerificationRequest.objects.create(
                    reference_number=ref_num,
                    requester=requester,
                    target_subject=target_subject,
                    verification_type=verification_type,
                    status='pending',
                    notes=notes.strip() if notes else ""
                )

                AuditLog.objects.create(
                    report=None,
                    action="VERIFICATION_REQUEST_CREATED",
                    performed_by=requester,
                    ip_address=ip_address,
                    details={
                        "verification_reference": ref_num,
                        "verification_type": verification_type,
                        "subject_type": subject_type,
                        "has_identifier": bool(identifier_hash)
                    }
                )

                # Celery email notification strictly on transaction commit
                requester_email = getattr(requester, 'email', None)
                if requester_email:
                    subject = f"VerifyNG Notice: Verification Request [{ref_num}] Received"
                    body = (
                        f"Hello,\n\n"
                        f"Your verification request [{ref_num}] has been submitted and registered in our queue.\n"
                        f"Our verification officers will review the submission. You can track progress in your portal.\n\n"
                        f"VerifyNG Trust & Safety Team"
                    )
                    transaction.on_commit(
                        lambda: send_email_notification_task.delay(requester_email, subject, body)
                    )

                return verif_request

        except IntegrityError:
            if attempt == max_retries - 1:
                raise
            continue


def claim_verification_request(
    reference_number: str,
    officer_user,
    ip_address: str = None
) -> VerificationRequest:
    """
    Concurrency-safe claim transitioning status from 'pending' to 'in_progress'.
    Uses row locking (select_for_update) to prevent race conditions.
    """
    with transaction.atomic():
        req = (
            VerificationRequest.objects.select_for_update()
            .get(reference_number=reference_number)
        )

        if req.status != 'pending':
            raise ValidationError(
                f"Cannot claim verification request in status '{req.status}'. Only 'pending' requests can be claimed."
            )

        req.status = 'in_progress'
        req.save(update_fields=['status', 'updated_at'])

        AuditLog.objects.create(
            report=None,
            action="VERIFICATION_STATUS_TRANSITION_PENDING_TO_IN_PROGRESS",
            performed_by=officer_user,
            ip_address=ip_address,
            details={
                "verification_reference": req.reference_number,
                "previous_status": "pending",
                "new_status": "in_progress",
                "officer": officer_user.username,
            }
        )

        return req


def complete_verification_request(
    reference_number: str,
    officer_user,
    outcome: str,
    summary: str,
    details: dict = None,
    ip_address: str = None
) -> VerificationResult:
    """
    Atomically saves VerificationResult and marks request 'completed'.
    Validates outcome choices and protects against duplicate result records.
    """
    valid_outcomes = dict(VerificationResult.OUTCOME_CHOICES)
    if outcome not in valid_outcomes:
        raise ValidationError(f"Invalid outcome: {outcome}. Allowed: {list(valid_outcomes.keys())}")

    if not summary or not summary.strip():
        raise ValidationError("Verification summary is required.")

    if details is None:
        details = {}

    with transaction.atomic():
        req = (
            VerificationRequest.objects.select_for_update()
            .get(reference_number=reference_number)
        )

        if req.status != 'in_progress':
            raise ValidationError(
                f"Cannot complete verification request in status '{req.status}'. Request must be 'in_progress'."
            )

        if hasattr(req, 'result'):
            raise ValidationError("A VerificationResult has already been recorded for this request.")

        result = VerificationResult.objects.create(
            request=req,
            verified_by=officer_user,
            outcome=outcome,
            summary=summary.strip(),
            details=details,
            verified_at=timezone.now()
        )

        req.status = 'completed'
        req.save(update_fields=['status', 'updated_at'])

        AuditLog.objects.create(
            report=None,
            action="VERIFICATION_REQUEST_COMPLETED",
            performed_by=officer_user,
            ip_address=ip_address,
            details={
                "verification_reference": req.reference_number,
                "outcome": outcome,
                "officer": officer_user.username,
            }
        )

        # Notify requester via Celery on commit without disclosing sensitive findings
        requester_email = getattr(req.requester, 'email', None)
        if requester_email:
            ref = req.reference_number
            subject = f"VerifyNG Notice: Verification Request [{ref}] Completed"
            body = (
                f"Hello,\n\n"
                f"The review for verification request [{ref}] has been completed by a verification officer.\n"
                f"You may now view the official outcome and summary in your VerifyNG portal.\n\n"
                f"VerifyNG Trust & Safety Team"
            )
            transaction.on_commit(
                lambda: send_email_notification_task.delay(requester_email, subject, body)
            )

        return result


def reject_verification_request(
    reference_number: str,
    officer_user,
    reason: str,
    ip_address: str = None
) -> VerificationRequest:
    """
    Atomically transitions an 'in_progress' request to 'rejected'.
    Stores officer rejection reason strictly in AuditLog to avoid polluting requester notes.
    """
    if not reason or not reason.strip():
        raise ValidationError("Rejection reason is required.")

    with transaction.atomic():
        req = (
            VerificationRequest.objects.select_for_update()
            .get(reference_number=reference_number)
        )

        if req.status != 'in_progress':
            raise ValidationError(
                f"Cannot reject verification request in status '{req.status}'. Request must be 'in_progress'."
            )

        req.status = 'rejected'
        req.save(update_fields=['status', 'updated_at'])

        AuditLog.objects.create(
            report=None,
            action="VERIFICATION_REQUEST_REJECTED",
            performed_by=officer_user,
            ip_address=ip_address,
            details={
                "verification_reference": req.reference_number,
                "rejection_reason": reason.strip(),
                "officer": officer_user.username,
            }
        )

        requester_email = getattr(req.requester, 'email', None)
        if requester_email:
            ref = req.reference_number
            subject = f"VerifyNG Notice: Verification Request [{ref}] Declined"
            body = (
                f"Hello,\n\n"
                f"Your verification request [{ref}] could not be completed and has been closed.\n"
                f"Please sign in to your VerifyNG member portal for further details or submit updated information.\n\n"
                f"VerifyNG Trust & Safety Team"
            )
            transaction.on_commit(
                lambda: send_email_notification_task.delay(requester_email, subject, body)
            )

        return req
