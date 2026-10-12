
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



# ── W-08: Certificate Service Layer ───────────────────────────────────────────
from verification.models import VerificationCertificate, CertificateQueryLog
from payments.models import Transaction
from reports.models import AuditLog


def get_certificate_query_price(check_level: str) -> int:
    """
    Returns query price in kobo.
    Employment Check: ₦50 (5000 kobo)
    Enhanced Check:   ₦100 (10000 kobo)
    """
    return 10000 if check_level == 'enhanced' else 5000


def create_certificate_application(holder, check_level: str, ip_address: str = None):
    """
    Creates a VerificationCertificate in 'pending' status.
    Does not activate — activation requires NIN verification by an officer.
    Logs the application event.
    Returns the created certificate.
    """
    from identities.models import SubjectEntity

    # Resolve or create the SubjectEntity for this user
    subject, _ = SubjectEntity.objects.get_or_create(
        user=holder,
        defaults={'subject_type': 'individual'}
    )

    certificate = VerificationCertificate.objects.create(
        subject=subject,
        holder=holder,
        check_level=check_level,
        status='pending',
    )

    AuditLog.objects.create(
        report=None,
        action='CERTIFICATE_APPLICATION_SUBMITTED',
        performed_by=holder,
        ip_address=ip_address,
        details={
            'certificate_id': certificate.certificate_id,
            'check_level': check_level,
        }
    )

    return certificate


def process_certificate_query(
    certificate,
    queried_by,
    transaction_reference: str,
    ip_address: str = None,
    purpose: str = 'other',
    organisation_name: str = '',
):
    """
    Validates payment, builds the result snapshot, and writes an
    immutable CertificateQueryLog row.

    Rules:
    - Transaction must exist, belong to queried_by, and status == 'success'
    - One log row is written per successful query — never updated
    - result_snapshot captures counts at the moment of query

    Returns the CertificateQueryLog instance.
    Raises ValidationError on any failure.
    """
    from django.core.exceptions import ValidationError

    # 1. Validate payment
    try:
        transaction = Transaction.objects.get(
            reference=transaction_reference,
            user=queried_by,
            status='success',
        )
    except Transaction.DoesNotExist:
        raise ValidationError(
            "Payment could not be confirmed. "
            "Please complete payment before viewing this certificate."
        )

    # 2. Build immutable result snapshot (counts only — data minimisation)
    fraud_count = 0
    misconduct_count = 0
    try:
        from reports.models import FraudReport
        fraud_count = FraudReport.objects.filter(
            subject=certificate.subject,
            status='verified'
        ).count()
    except Exception:
        pass

    result_snapshot = {
        'certificate_id': certificate.certificate_id,
        'certificate_status': certificate.status,
        'check_level': certificate.check_level,
        'is_valid': certificate.is_valid,
        'fraud_report_count': fraud_count,
        'misconduct_report_count': misconduct_count,
        'queried_at': tz.now().isoformat(),
    }

    # 3. Write the immutable log row
    query_log = CertificateQueryLog.objects.create(
        certificate=certificate,
        queried_by=queried_by,
        payment=transaction,
        ip_address=ip_address,
        purpose=purpose,
        organisation_name=organisation_name,
        result_snapshot=result_snapshot,
    )

    return query_log


def get_certificate_pdf_url(certificate) -> str:
    """
    Returns a time-limited signed Cloudinary URL for the certificate PDF.
    Reuses the existing CloudinaryEvidenceStorage service layer.
    
    Returns empty string if no PDF has been generated yet.
    """
    if not certificate.pdf_file:
        return ''

    from reports.storage_services import get_storage_service, StorageError

    try:
        storage = get_storage_service()
        return storage.generate_signed_url(
            public_id=certificate.pdf_file,
            format='pdf',
            resource_type='raw',      # PDFs are raw in Cloudinary
            expires_in_seconds=300,   # 5 minutes
        )
    except StorageError:
        logger.error(
            "Failed to generate signed URL for certificate %s",
            certificate.certificate_id
        )
        return ''

def upload_certificate_pdf(certificate, pdf_file_obj) -> str:
    """
    Uploads a generated certificate PDF to Cloudinary.
    Stores the returned public_id on the certificate record.
    
    Args:
        certificate: VerificationCertificate instance
        pdf_file_obj: file-like object of the generated PDF
        
    Returns:
        public_id string from Cloudinary
    """
    from reports.storage_services import get_storage_service, StorageError

    storage = get_storage_service()
    result = storage.upload_evidence(
        file_obj=pdf_file_obj,
        folder_prefix='certificates'    # separate folder from evidence/
    )
    public_id = result['public_id']

    certificate.pdf_file = public_id
    certificate.save(update_fields=['pdf_file', 'updated_at'])

    return public_id




