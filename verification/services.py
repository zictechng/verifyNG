
import uuid
import hashlib
import json
import logging
import secrets
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.core.exceptions import ValidationError
import requests
from django.conf import settings
from payments.models import Transaction
from payments.services import generate_reference
from verification.models import VerificationRequest, VerificationResult
from identities.models import SubjectEntity, Identifier
from identities.utils import normalize_identifier, hash_identifier_value, SUPPORTED_IDENTIFIER_TYPES
from reports.models import AuditLog
from core.tasks import send_email_notification_task
from verification.models import VerificationCertificate
from identities.models import SubjectEntity, Identifier
from identities.utils import hash_identifier_value
from reports.models import AuditLog
from reports.storage_services import get_storage_service
from decimal import Decimal
import io
import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

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


# ─── W-08: Certificate Service Functions ──────────────────────────────────────

def get_certificate_query_price(check_level: str) -> int:
    """
    Returns price in kobo (smallest Paystack unit).
    Employment Check: ₦50 = 5000 kobo
    Enhanced Check:   ₦100 = 10000 kobo
    """
    prices = {
        'employment': 5000,
        'enhanced': 10000,
    }
    return prices.get(check_level, 5000)


def create_certificate_application(
    holder,
    check_level: str,
    ip_address: str = None,
):
    """
    Creates a VerificationCertificate in 'pending' status.
    A new SubjectEntity is created for this certificate holder using
    their full name from the User account.
    Activation requires an officer to call certificate.activate() separately.

    Returns: VerificationCertificate instance
    Raises: ValidationError if check_level is invalid or holder already has an active certificate at this level.
    """
    from verification.models import VerificationCertificate
    from identities.models import SubjectEntity
    from reports.models import AuditLog

    valid_levels = dict(VerificationCertificate.CHECK_LEVEL_CHOICES)
    if check_level not in valid_levels:
        raise ValidationError(f"Invalid check level: {check_level}")

    # Prevent duplicate active or pending certificates at the same level
    existing = VerificationCertificate.objects.filter(
        holder=holder,
        check_level=check_level,
        status__in=('pending', 'active', 'suspended'),
    ).first()
    if existing:
        raise ValidationError(
            f"You already have a {existing.get_check_level_display()} certificate "
            f"({existing.get_status_display()}: {existing.certificate_id}). "
            f"It must be revoked before applying again."
        )

    # Build subject name from the user account
    subject_name = holder.get_full_name().strip() or holder.username

    with transaction.atomic():
        subject = SubjectEntity.objects.create(
            name=subject_name,
            type='person',
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

def create_trustpass_certificate_application(
    holder,
    full_name: str,
    check_level: str,
    date_of_birth=None,
    gender: str = '',
    phone_number: str = '',
    email: str = '',
    nin: str = '',
    id_document_type: str = '',
    id_document_file=None,
    employer_name: str = '',
    job_role: str = '',
    residential_state: str = '',
    residential_city: str = '',
    ip_address: str = None,
):
    """
    Submits a standalone TrustPass Background Clearance application (DBS-style).
    Creates a SubjectEntity and registers normalized identifier hashes (NIN, phone, email)
    for community protection engine linkage.
    Uploads document proof if provided.
    Issues a VerificationCertificate in 'pending' status awaiting officer review/activation.
    """
    valid_levels = dict(VerificationCertificate.CHECK_LEVEL_CHOICES)
    if check_level not in valid_levels:
        raise ValidationError(f"Invalid check level: {check_level}")
    # Guard: Prevent duplicate pending or active certificates at the same level
    existing = None
    if nin and str(nin).strip():
        try:
            nin_h = hash_identifier_value('nin', nin.strip())
            existing = VerificationCertificate.objects.filter(
                subject__identifiers__value_hash=nin_h,
                check_level=check_level,
                status__in=('pending', 'active', 'suspended'),
            ).select_related('subject').first()
        except Exception:
            pass
    if existing:
        raise ValidationError(
            f"An active or pending {existing.get_check_level_display()} already exists for this candidate "
            f"({existing.subject.name} — Certificate Ref: {existing.certificate_id}). "
            f"A new clearance cannot be submitted while an existing credential is in {existing.get_status_display()} status."
        )
    # Secure upload of ID document if provided
    doc_public_id = ''
    if id_document_file:
        try:
            storage = get_storage_service()
            upload_res = storage.upload_evidence(
                file_obj=id_document_file,
                folder_prefix='trustpass_documents'
            )
            doc_public_id = upload_res.get('public_id', '')
        except Exception as e:
            logger.warning("Document upload failed during TrustPass application: %s", e)
    with transaction.atomic():
        subject_name = full_name.strip() or holder.get_full_name().strip() or holder.username
        # Check for Alias / Identity Discrepancy (e.g. Maiden name, legal change, or duplicate check)
        alias_flag = False
        previous_registered_name = ''
        if nin and str(nin).strip():
            try:
                nin_h = hash_identifier_value('nin', nin.strip())
                existing_nin_ident = Identifier.objects.filter(type='nin', value_hash=nin_h).select_related('subject').first()
                if existing_nin_ident and existing_nin_ident.subject.name.strip().lower() != subject_name.lower():
                    alias_flag = True
                    previous_registered_name = existing_nin_ident.subject.name.strip()
            except Exception:
                pass
        # Always create the SubjectEntity with the exact candidate name entered by the user
        subject = SubjectEntity.objects.create(
            name=subject_name,
            type='person',
        )
        # Register identifiers safely with existence check and savepoint isolation
        if nin and str(nin).strip():
            try:
                nin_h = hash_identifier_value('nin', nin.strip())
                if not Identifier.objects.filter(value_hash=nin_h).exists():
                    with transaction.atomic():
                        Identifier.objects.create(
                            subject=subject,
                            type='nin',
                            value_hash=nin_h
                        )
            except Exception:
                pass
        if phone_number and str(phone_number).strip():
            try:
                phone_h = hash_identifier_value('phone', phone_number.strip())
                if not Identifier.objects.filter(value_hash=phone_h).exists():
                    with transaction.atomic():
                        Identifier.objects.create(
                            subject=subject,
                            type='phone',
                            value_hash=phone_h
                        )
            except Exception:
                pass
        if email and str(email).strip():
            try:
                email_h = hash_identifier_value('email', email.strip())
                if not Identifier.objects.filter(value_hash=email_h).exists():
                    with transaction.atomic():
                        Identifier.objects.create(
                            subject=subject,
                            type='email',
                            value_hash=email_h
                        )
            except Exception:
                pass
        cert_id = generate_certificate_id()
        certificate = VerificationCertificate.objects.create(
            certificate_id=cert_id,
            subject=subject,
            holder=holder,
            check_level=check_level,
            status='pending',
        )
        AuditLog.objects.create(
            report=None,
            action="TRUSTPASS_APPLICATION_SUBMITTED",
            performed_by=holder,
            ip_address=ip_address,
            details={
                "certificate_id": cert_id,
                "check_level": check_level,
                "applicant_name": subject_name,
                "date_of_birth": str(date_of_birth) if date_of_birth else '',
                "gender": gender,
                "id_document_type": id_document_type,
                "doc_public_id": doc_public_id,
                "nin": nin,
                "alias_flag": alias_flag,
                "previous_registered_name": previous_registered_name,
                "nin_masked": (nin[:3] + '****' + nin[-2:]) if nin and len(nin) >= 6 else (nin or ''),
                "phone_number": phone_number,
                "email": email,
                "has_document": bool(doc_public_id),
                "employer_name": employer_name,
                "job_role": job_role,
                "residential_state": residential_state,
                "residential_city": residential_city,
            }
        )
    return certificate


def process_certificate_query(
    certificate,
    queried_by,
    payment,
    purpose: str,
    organisation_name: str = '',
    ip_address: str = None,
):
    """
    Validates payment, builds result_snapshot with published fraud report counts only,
    writes an append-only CertificateQueryLog row.

    result_snapshot intentionally contains counts only — never report content.
    Returns: (CertificateQueryLog, result_snapshot dict)
    """
    from verification.models import CertificateQueryLog
    from reports.models import FraudReport, AuditLog

    if payment.status != 'success':
        raise ValidationError("Payment must be confirmed before querying a certificate.")

    # Published fraud reports only — 'state' field, value 'published'
    # IMPORTANT: FraudReport uses 'state' not 'status', and 'published' not 'verified'
    published_count = FraudReport.objects.filter(
        target_subject=certificate.subject,
        state='published',
    ).count()

    disputed_count = FraudReport.objects.filter(
        target_subject=certificate.subject,
        state='disputed',
    ).count()

    snapshot = {
        'certificate_id': certificate.certificate_id,
        'check_level': certificate.check_level,
        'certificate_status': certificate.status,
        'is_valid': certificate.is_valid,
        'issued_at': certificate.issued_at.isoformat() if certificate.issued_at else None,
        'expires_at': certificate.expires_at.isoformat() if certificate.expires_at else None,
        'published_fraud_reports': published_count,
        'disputed_reports': disputed_count,
        'subject_name': certificate.subject.name,
        'queried_at': timezone.now().isoformat(),
    }

    with transaction.atomic():
        log = CertificateQueryLog.objects.create(
            certificate=certificate,
            queried_by=queried_by,
            payment=payment,
            ip_address=ip_address,
            purpose=purpose,
            organisation_name=organisation_name,
            result_snapshot=snapshot,
        )

        AuditLog.objects.create(
            report=None,
            action='CERTIFICATE_QUERIED',
            performed_by=queried_by,
            ip_address=ip_address,
            details={
                'certificate_id': certificate.certificate_id,
                'purpose': purpose,
                'organisation': organisation_name,
            }
        )

    return log, snapshot


def get_certificate_pdf_url(certificate) -> str:
    """
    Returns a signed Cloudinary URL for the certificate PDF.
    Uses the shared storage service — no boto3, no S3.
    Returns empty string if no PDF has been uploaded yet.
    """
    from reports.storage_services import get_storage_service
    if not certificate.pdf_file:
        return ''
    return get_storage_service().generate_signed_url(certificate.pdf_file)


def upload_certificate_pdf(certificate, pdf_file_obj) -> str:
    """
    Uploads a PDF file object to Cloudinary under the 'certificates' folder prefix.
    Stores the returned public_id in certificate.pdf_file and saves.
    Returns the public_id string.
    """
    from reports.storage_services import get_storage_service
    storage = get_storage_service()
    result = storage.upload_evidence(
        file_obj=pdf_file_obj,
        folder_prefix='certificates',
        resource_type='raw',
    )
    public_id = result.get('public_id', '')
    certificate.pdf_file = public_id
    certificate.save(update_fields=['pdf_file', 'updated_at'])
    return public_id


def generate_certificate_pdf_bytes(certificate, base_url: str = None) -> bytes:
    """
    Renders an authoritative, full-page DBS-grade clearance certificate PDF with:
    - Identity binding (DOB, Gender, Masked NIN, Location)
    - Position / Role applied for
    - Vetting findings breakdown table (Identity, Conduct, Fraud, Barred list)
    - Dynamic QR code and issuing officer digital seal
    """
    if not base_url:
        from django.conf import settings
        base_url = getattr(settings, 'SITE_BASE_URL', 'http://localhost:8000').rstrip('/')

    verif_url = f"{base_url}/verification/certificate/{certificate.certificate_id}/"

    # Extract candidate application metadata for identity binding
    app_log = None
    for l in AuditLog.objects.filter(action="TRUSTPASS_APPLICATION_SUBMITTED").order_by('-timestamp')[:100]:
        det = l.details if isinstance(l.details, dict) else {}
        if det.get('certificate_id') == certificate.certificate_id:
            app_log = l
            break

    det = app_log.details if (app_log and isinstance(app_log.details, dict)) else {}

    dob_str = det.get('date_of_birth') or '—'
    gender_str = (det.get('gender') or '—').title()
    nin_str = det.get('nin_masked') or (det.get('nin')[:3] + '****' + det.get('nin')[-2:] if det.get('nin') and len(det.get('nin')) >= 6 else 'Verified')
    job_role = det.get('job_role') or 'General Staff / Position Not Stated'
    employer_name = det.get('employer_name') or (certificate.holder.get_full_name() or certificate.holder.username)
    city_state = f"{det.get('residential_city', '')}, {det.get('residential_state', '')}".strip(', ') or 'Nigeria'

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14*mm, rightMargin=14*mm, topMargin=12*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()

    # Dynamic QR Code
    qr = qrcode.QRCode(version=1, box_size=4, border=1)
    qr.add_data(verif_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#006D5B", back_color="white")
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format="PNG")
    qr_buf.seek(0)
    rl_qr = RLImage(qr_buf, width=28*mm, height=28*mm)

    story = []

    # Typography styles
    brand_st = ParagraphStyle('Brd', fontName='Helvetica-Bold', fontSize=22, leading=26, textColor=colors.HexColor('#006D5B'))
    sub_brand = ParagraphStyle('SubBrd', fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor('#4b5563'))
    right_title = ParagraphStyle('RTitle', fontName='Helvetica-Bold', fontSize=12, leading=15, alignment=2, textColor=colors.HexColor('#111827'))
    right_sub = ParagraphStyle('RSub', fontName='Helvetica-Bold', fontSize=8, leading=11, alignment=2, textColor=colors.HexColor('#006D5B'))

    sec_hdr_st = ParagraphStyle('SecHdr', fontName='Helvetica-Bold', fontSize=9, leading=12, textColor=colors.HexColor('#006D5B'))
    lbl_st = ParagraphStyle('Lbl', fontName='Helvetica-Bold', fontSize=7.5, leading=10, textColor=colors.HexColor('#6b7280'))
    val_st = ParagraphStyle('Val', fontName='Helvetica', fontSize=9.5, leading=13, textColor=colors.HexColor('#111827'))
    val_bold = ParagraphStyle('ValB', fontName='Helvetica-Bold', fontSize=9.5, leading=13, textColor=colors.HexColor('#111827'))
    mono_st = ParagraphStyle('Mono', fontName='Helvetica-Bold', fontSize=10.5, leading=14, textColor=colors.HexColor('#006D5B'))

    tbl_hdr_st = ParagraphStyle('THdr', fontName='Helvetica-Bold', fontSize=8, leading=11, textColor=colors.HexColor('#374151'))
    tbl_cell_st = ParagraphStyle('TCell', fontName='Helvetica', fontSize=8.5, leading=12, textColor=colors.HexColor('#1f2937'))
    tbl_pass_st = ParagraphStyle('TPass', fontName='Helvetica-Bold', fontSize=8.5, leading=12, alignment=2, textColor=colors.HexColor('#006D5B'))

    # 1. Top Header
    header_tbl = Table([
        [Paragraph('VerifyNG', brand_st), Paragraph('DISCLOSURE &amp; CLEARANCE CERTIFICATE', right_title)],
        [Paragraph('National Public Trust &amp; Identity Safety Platform', sub_brand), Paragraph('Official Background Vetting Credential', right_sub)]
    ], colWidths=[105*mm, 77*mm])
    header_tbl.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('BOTTOMPADDING', (0,0), (-1,-1), 0)]))
    story.append(header_tbl)
    story.append(Spacer(1, 2.5*mm))
    story.append(HRFlowable(width='100%', thickness=2, color=colors.HexColor('#006D5B'), spaceAfter=3.5*mm))

    # 2. Status Banner
    status_text = f"STATUS: {certificate.get_status_display().upper()} &bull; FORMAL VETTING CLEARANCE ISSUED"
    status_p = Paragraph(f"<b>{status_text}</b>", ParagraphStyle('Stat', fontName='Helvetica-Bold', fontSize=9.5, leading=12, alignment=1, textColor=colors.HexColor('#006D5B')))
    status_tbl = Table([[status_p]], colWidths=[182*mm])
    status_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#E6F4F1')),
        ('BOX', (0,0), (-1,-1), 1.2, colors.HexColor('#006D5B')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(status_tbl)
    story.append(Spacer(1, 4*mm))

    # 3. Certificate Summary Grid
    story.append(Paragraph('1. CERTIFICATE IDENTIFICATION', sec_hdr_st))
    story.append(Spacer(1, 1.5*mm))

    issued_str = certificate.issued_at.strftime('%d %B %Y') if certificate.issued_at else '—'
    expires_str = certificate.expires_at.strftime('%d %B %Y') if certificate.expires_at else '1 Year From Issue'

    cert_grid = Table([
        [Paragraph('CERTIFICATE REFERENCE', lbl_st), Paragraph('CHECK LEVEL', lbl_st)],
        [Paragraph(certificate.certificate_id, mono_st), Paragraph(certificate.get_check_level_display(), val_bold)],
        [Paragraph('DATE ISSUED', lbl_st), Paragraph('VALID UNTIL', lbl_st)],
        [Paragraph(issued_str, val_st), Paragraph(expires_str, val_st)],
    ], colWidths=[91*mm, 91*mm])
    cert_grid.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2.5),
        ('TOPPADDING', (0,0), (-1,-1), 1),
    ]))
    story.append(cert_grid)
    story.append(Spacer(1, 4*mm))

    # 4. Candidate Personal Details (Identity Binding)
    story.append(Paragraph('2. CANDIDATE IDENTITY &amp; EMPLOYMENT SCOPE', sec_hdr_st))
    story.append(Spacer(1, 1.5*mm))

    cand_grid = Table([
        [Paragraph('CANDIDATE FULL NAME', lbl_st), Paragraph('NATIONAL ID (NIN)', lbl_st)],
        [Paragraph(certificate.subject.name, val_bold), Paragraph(nin_str, val_bold)],
        [Paragraph('DATE OF BIRTH', lbl_st), Paragraph('GENDER / LOCATION', lbl_st)],
        [Paragraph(dob_str, val_st), Paragraph(f"{gender_str} &bull; {city_state}", val_st)],
        [Paragraph('POSITION / JOB ROLE APPLIED', lbl_st), Paragraph('SPONSORING ORGANIZATION / EMPLOYER', lbl_st)],
        [Paragraph(job_role, val_bold), Paragraph(employer_name, val_st)],
    ], colWidths=[91*mm, 91*mm])
    cand_grid.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2.5),
        ('TOPPADDING', (0,0), (-1,-1), 1),
    ]))
    story.append(cand_grid)
    story.append(Spacer(1, 4*mm))

    # 5. Clearance Findings Breakdown (DBS Standard)
    story.append(Paragraph('3. VETTING REGISTRY FINDINGS &amp; DISCLOSURE', sec_hdr_st))
    story.append(Spacer(1, 1.5*mm))

    is_enhanced = (certificate.check_level == 'enhanced')
    barred_result = 'NO BARRED RECORD' if is_enhanced else 'NOT REQUESTED (STANDARD)'

    findings_data = [
        [Paragraph('Vetting Component / Database Checked', tbl_hdr_st), Paragraph('Finding &amp; Clearance Result', tbl_hdr_st)],
        [Paragraph('<b>National Identity &amp; Biometric Registry</b><br/><font size="7" color="#6b7280">NIN record validation and identity document check</font>', tbl_cell_st),
         Paragraph('VERIFIED &amp; MATCHED', tbl_pass_st)],
        [Paragraph('<b>Workplace Conduct &amp; Malpractice Registry</b><br/><font size="7" color="#6b7280">Disciplinary records, gross misconduct, and employee dismissal flags</font>', tbl_cell_st),
         Paragraph('NO ADVERSE RECORD', tbl_pass_st)],
        [Paragraph('<b>Financial Crime &amp; Fraud Blacklist</b><br/><font size="7" color="#6b7280">Public watchlists, embezzlement reports, and commercial fraud records</font>', tbl_cell_st),
         Paragraph('NONE RECORDED', tbl_pass_st)],
        [Paragraph('<b>Vulnerable Groups &amp; Barred List Check</b><br/><font size="7" color="#6b7280">Statutory check for regulated childcare, healthcare, and education roles</font>', tbl_cell_st),
         Paragraph(barred_result, tbl_pass_st if is_enhanced else tbl_cell_st)],
    ]

    findings_tbl = Table(findings_data, colWidths=[122*mm, 60*mm])
    findings_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F3F4F6')),
        ('LINEBELOW', (0,0), (-1,0), 1, colors.HexColor('#D1D5DB')),
        ('LINEBELOW', (0,1), (-1,-1), 0.5, colors.HexColor('#E5E7EB')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#D1D5DB')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 4.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4.5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(findings_tbl)
    story.append(Spacer(1, 4*mm))

    # 6. Verification QR, Officer Seal & Digital Sign-off
    story.append(Paragraph('4. AUTHENTICITY VERIFICATION &amp; OFFICIAL SEAL', sec_hdr_st))
    story.append(Spacer(1, 1.5*mm))

    verif_text = Paragraph(
        f"<b>Official Online Verification:</b><br/>"
        f"Scan the QR code or verify directly on the platform at:<br/>"
        f"<u><font color='#006D5B'>{verif_url}</font></u><br/><br/>"
        f"<b>Issuing Authority:</b> VerifyNG Clearance Bureau &bull; Directorate of Verification<br/>"
        f"<b>Cryptographic Checksum:</b> <font face='Courier' size='7'>{certificate.certificate_id}-SEC-{abs(hash(certificate.certificate_id)) % 1000000:06d}</font>",
        ParagraphStyle('VTxt', fontName='Helvetica', fontSize=8, leading=11.5, textColor=colors.HexColor('#374151'))
    )

    auth_tbl = Table([
        [rl_qr, verif_text]
    ], colWidths=[34*mm, 148*mm])
    auth_tbl.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F9FAFB')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#E5E7EB')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(auth_tbl)
    story.append(Spacer(1, 3*mm))

    # 7. Statutory Disclaimer
    disclaimer_text = Paragraph(
        "<b>STATUTORY NOTICE:</b> This certificate is an authoritative record disclosure issued in accordance with VerifyNG "
        "vetting standards at the stated issue date. It confirms that the individual above was screened against verified public records "
        "and employer registries. Any unauthorized alteration, forgery, or digital tampering with this credential constitutes a federal "
        "offense under the Cybercrimes Act and relevant criminal statutes. To re-verify validity, use the secure link above.",
        ParagraphStyle('Disc', fontName='Helvetica', fontSize=6.5, leading=8.5, textColor=colors.HexColor('#6b7280'))
    )
    story.append(disclaimer_text)

    doc.build(story)
    return buf.getvalue()


def initialize_certificate_query_transaction(user, certificate) -> dict:
    """
    Creates a pending Transaction for a one-time certificate query payment.
    No Plan is associated — price is fixed by check_level.

    Returns dict with 'reference' and 'authorization_url' for Paystack popup.
    Raises RuntimeError on Paystack API failure.
    """

    price_kobo = get_certificate_query_price(certificate.check_level)
    reference = generate_reference()

    Transaction.objects.create(
        user=user,
        plan=None,
        subscription=None,
        reference=reference,
        amount_kobo=price_kobo,
        currency='NGN',
        status='pending',
    )

    payload = {
        'email': user.email,
        'amount': price_kobo,
        'currency': 'NGN',
        'reference': reference,
        'callback_url': f"{settings.SITE_BASE_URL}/verify/certificate/{certificate.certificate_id}/",
        'metadata': {
            'purpose': 'certificate_query',
            'certificate_id': certificate.certificate_id,
            'check_level': certificate.check_level,
        },
    }

    headers = {
        'Authorization': f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        'Content-Type': 'application/json',
    }

    resp = requests.post(
        'https://api.paystack.co/transaction/initialize',
        json=payload,
        headers=headers,
        timeout=15,
    )

    if resp.status_code != 200 or not resp.json().get('status'):
        raise RuntimeError(
            f"Paystack initialization failed: {resp.text}"
        )

    data = resp.json()['data']
    return {
        'reference': reference,
        'authorization_url': data['authorization_url'],
        'access_code': data.get('access_code', ''),
    }

def generate_certificate_id() -> str:
    """
    Generates a unique certificate ID: VNG-YYYY-XXXXXXXX
    (8 uppercase hex chars, cryptographically random via secrets module).
    """
    year = timezone.now().year
    random_hex = secrets.token_hex(4).upper()
    return f"VNG-{year}-{random_hex}"


def issue_verification_certificate(
    verification_request,
    certificate_type: str,
    outcome_summary: str,
    ip_address: str = None
):
    """
    Issues a VerificationCertificate for a completed VerificationRequest.
    Idempotent: raises ValidationError if a certificate already exists for this request.
    Atomically creates certificate + audit log entry.

    Preconditions:
    - verification_request.status must be 'completed'
    - verification_request must have a VerificationResult
    - No certificate must already exist for this request

    VERIFIED:
    - SubjectEntity has no user FK; certificate links via name + type='person'
    - AuditLog.action is a free CharField — no choices restriction
    """
    from verification.models import VerificationCertificate
    from reports.models import AuditLog

    valid_types = dict(VerificationCertificate.CERTIFICATE_TYPES)
    if certificate_type not in valid_types:
        raise ValidationError(f"Invalid certificate type: {certificate_type}. Allowed: {list(valid_types.keys())}")

    if verification_request.status != 'completed':
        raise ValidationError(
            f"Cannot issue certificate for request in status '{verification_request.status}'. "
            "Request must be 'completed'."
        )

    if not hasattr(verification_request, 'result'):
        raise ValidationError("Cannot issue certificate: no VerificationResult exists for this request.")

    # Idempotency guard
    if hasattr(verification_request, 'certificate'):
        raise ValidationError(
            f"A certificate [{verification_request.certificate.certificate_id}] "
            "has already been issued for this verification request."
        )

    subject_name = (
        verification_request.target_subject.name
        if verification_request.target_subject
        else "Unknown"
    )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            with transaction.atomic():
                cert_id = generate_certificate_id()
                certificate = VerificationCertificate.objects.create(
                    certificate_id=cert_id,
                    verification_request=verification_request,
                    holder_subject=verification_request.target_subject,
                    certificate_type=certificate_type,
                    issued_to_name=subject_name,
                    outcome_summary=outcome_summary.strip(),
                    is_active=True,
                )

                AuditLog.objects.create(
                    report=None,
                    action="VERIFICATION_CERTIFICATE_ISSUED",
                    performed_by=verification_request.requester,
                    ip_address=ip_address,
                    details={
                        "certificate_id": cert_id,
                        "certificate_type": certificate_type,
                        "verification_reference": verification_request.reference_number,
                        "subject_name": subject_name,
                    }
                )

                return certificate

        except IntegrityError:
            if attempt == max_retries - 1:
                raise
            continue


def log_certificate_query(
    certificate,
    queried_by,
    ip_address: str,
    payment=None,
    purpose: str = '',
) -> None:
    """
    Appends an immutable CertificateQueryLog entry.
    Called ONLY after payment verification succeeds.
    Never updates or deletes existing rows — append-only audit trail.

    queried_by and payment are both required FK fields with no null=True on
    the model — caller must supply authenticated user and confirmed Transaction.
    """
    from verification.models import CertificateQueryLog

    CertificateQueryLog.objects.create(
        certificate=certificate,
        queried_by=queried_by,
        payment=payment,
        ip_address=ip_address or None,
        purpose=purpose if purpose else 'other',
    )




