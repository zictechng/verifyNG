import uuid
import os
from django.utils import timezone
from django.db import transaction, IntegrityError
from reports.models import FraudReport, ReportEvidence, AuditLog, Dispute
from identities.models import SubjectEntity, Identifier, BusinessProfile
from identities.utils import hash_identifier_value
from reports.storage_services import get_storage_service, StorageError
from core.tasks import send_email_notification_task
from notifications import email_templates


def generate_report_reference_number():
    """Generates unique reference: VNG-YYYYMMDD-XXXX"""
    today_str = timezone.now().strftime('%Y%m%d')
    unique_suffix = uuid.uuid4().hex[:4].upper()
    return f"VNG-{today_str}-{unique_suffix}"


def infer_evidence_file_type(filename, selected_type=None):
    """Infers ReportEvidence.file_type from selected_type or extension fallback."""
    valid_types = {'document', 'screenshot', 'receipt', 'chat_log', 'other'}
    if selected_type and selected_type in valid_types and selected_type != 'other':
        return selected_type
    ext = os.path.splitext(filename)[1].lower()
    if ext in ['.pdf', '.doc', '.docx']:
        return 'document'
    elif ext in ['.png', '.jpg', '.jpeg']:
        return 'screenshot'
    return 'other'


def create_fraud_report(reporter, subject_name, subject_type, title, allegation,
                        incident_date=None, evidence_file=None, evidence_type=None,
                        evidence_description="", suspect_phone=None,
                        suspect_bank_account=None, suspect_bank_name=None,
                        suspect_cac_number=None, suspect_email=None,
                        suspect_location=None, suspect_state=None, suspect_city=None):
    """
    Creates FraudReport and optional initial evidence atomically.
    Normalizes and registers provided suspect identifiers into identities.Identifier
    to ensure immediate lookup capability upon report publication.
    Uploads evidence to cloud/local storage before DB write.
    Cleans up uploaded asset if DB write fails.
    """
    storage = get_storage_service()
    uploaded_cloud_meta = None

    if evidence_file:
        try:
            uploaded_cloud_meta = storage.upload_evidence(evidence_file)
        except StorageError:
            raise

    max_retries = 3
    for attempt in range(max_retries):
        try:
            with transaction.atomic():
                # 1. Normalize and compute digests for provided identifiers
                provided_identifiers = []
                if suspect_phone and str(suspect_phone).strip():
                    try:
                        h = hash_identifier_value('phone', suspect_phone)
                        provided_identifiers.append(('phone', h))
                    except ValueError:
                        pass

                if suspect_bank_account and str(suspect_bank_account).strip():
                    try:
                        h = hash_identifier_value('account', suspect_bank_account)
                        provided_identifiers.append(('account', h))
                    except ValueError:
                        pass

                if suspect_cac_number and str(suspect_cac_number).strip():
                    try:
                        h = hash_identifier_value('cac', suspect_cac_number)
                        provided_identifiers.append(('cac', h))
                    except ValueError:
                        pass

                if suspect_email and str(suspect_email).strip():
                    try:
                        h = hash_identifier_value('email', suspect_email)
                        provided_identifiers.append(('email', h))
                    except ValueError:
                        pass

                # 2. Entity Deduplication: match existing subject by identifier hash
                subject = None
                if provided_identifiers:
                    hashes = [h for _, h in provided_identifiers]
                    matched_ident = Identifier.objects.filter(value_hash__in=hashes).select_related('subject').first()
                    if matched_ident:
                        subject = matched_ident.subject

                # If no matching subject exists, create new SubjectEntity
                if not subject:
                    subject = SubjectEntity.objects.create(
                        name=subject_name,
                        type=subject_type
                    )

                # 3. Associate all provided identifiers with subject
                for id_type, id_hash in provided_identifiers:
                    Identifier.objects.get_or_create(
                        value_hash=id_hash,
                        defaults={
                            'subject': subject,
                            'type': id_type,
                        }
                    )

                # 4. If business entity, populate/update BusinessProfile
                if subject.type == 'business' and (suspect_cac_number or suspect_location or suspect_state or suspect_city or suspect_email or suspect_phone):
                    addr_parts = [p for p in [suspect_location, suspect_city, suspect_state] if p and str(p).strip()]
                    full_address = ", ".join(addr_parts)
                    bp, created = BusinessProfile.objects.get_or_create(
                        subject=subject,
                        defaults={
                            'official_name': subject.name,
                            'registration_number': suspect_cac_number or '',
                            'address': full_address,
                            'contact_email': suspect_email or '',
                            'contact_phone': suspect_phone or '',
                        }
                    )
                    if not created:
                        updated_fields = []
                        if not bp.registration_number and suspect_cac_number:
                            bp.registration_number = suspect_cac_number
                            updated_fields.append('registration_number')
                        if not bp.address and full_address:
                            bp.address = full_address
                            updated_fields.append('address')
                        if not bp.contact_email and suspect_email:
                            bp.contact_email = suspect_email
                            updated_fields.append('contact_email')
                        if not bp.contact_phone and suspect_phone:
                            bp.contact_phone = suspect_phone
                            updated_fields.append('contact_phone')
                        if updated_fields:
                            bp.save(update_fields=updated_fields)

                # 5. Create FraudReport record
                ref_num = generate_report_reference_number()

                report = FraudReport(
                    reference_number=ref_num,
                    reporter=reporter,
                    target_subject=subject,
                    title=title,
                    allegation=allegation,
                    incident_date=incident_date,
                    state='submitted'
                )
                report._audit_logged = True
                report.save()

                AuditLog.objects.create(
                    report=report,
                    action="REPORT_SUBMITTED",
                    performed_by=reporter,
                    details={
                        "reference_number": report.reference_number,
                        "initial_state": report.state,
                        "target_subject_id": subject.id,
                        "identifiers_attached": [t for t, _ in provided_identifiers],
                        "suspect_context": {
                            "bank_name": suspect_bank_name or "",
                            "location": suspect_location or "",
                            "state": suspect_state or "",
                            "city": suspect_city or "",
                        }
                    }
                )

                if uploaded_cloud_meta:
                    file_type = infer_evidence_file_type(evidence_file.name, evidence_type)
                    ReportEvidence.objects.create(
                        report=report,
                        file=uploaded_cloud_meta['public_id'],
                        file_type=file_type,
                        description=evidence_description or "Initial submitted evidence",
                        is_confidential=True,
                        storage_provider=uploaded_cloud_meta['provider'],
                        storage_public_id=uploaded_cloud_meta['public_id'],
                        storage_resource_type=uploaded_cloud_meta['resource_type'],
                        storage_format=uploaded_cloud_meta['format']
                    )
                return report

        except IntegrityError as e:
            if attempt == max_retries - 1:
                if uploaded_cloud_meta:
                    try:
                        storage.delete_evidence(
                            uploaded_cloud_meta['public_id'],
                            uploaded_cloud_meta['resource_type']
                        )
                    except StorageError:
                        pass
                raise e
        except Exception as e:
            if uploaded_cloud_meta:
                try:
                    storage.delete_evidence(
                        uploaded_cloud_meta['public_id'],
                        uploaded_cloud_meta['resource_type']
                    )
                except StorageError:
                    pass
            raise e
@transaction.atomic
def transition_report_state(report, new_state, actor=None, ip_address=None, moderation_notes=None):
    """
    Formally transitions a FraudReport state, recording an atomic AuditLog with actor attribution.
    Enforces transaction.on_commit() to dispatch notifications only upon successful commit.
    """
    valid_states = dict(FraudReport.STATES)
    if new_state not in valid_states:
        raise ValueError(f"Invalid report state '{new_state}'. Allowed: {list(valid_states.keys())}")

    previous_state = report.state
    if previous_state == new_state:
        return report

    report.state = new_state
    if moderation_notes is not None:
        report.moderation_notes = moderation_notes

    report._audit_logged = True
    report._notification_dispatched = True
    report.save(update_fields=['state', 'moderation_notes', 'updated_at'])

    AuditLog.objects.create(
        report=report,
        action=f"STATE_TRANSITION_{previous_state.upper()}_TO_{new_state.upper()}",
        performed_by=actor,
        ip_address=ip_address,
        details={
            "previous_state": previous_state,
            "new_state": new_state,
            "reference_number": report.reference_number,
            "moderation_notes": moderation_notes or ""
        }
    )

    # Dispatch branded HTML email notification on successful transaction commit
    reporter_email = getattr(report.reporter, 'email', None)
    if reporter_email:
        ref = report.reference_number
        username = (
            getattr(report.reporter, 'get_full_name', lambda: '')() or
            report.reporter.username
        )
        if new_state in ('published', 'rejected', 'archived', 'under_review', 'resolved', 'restricted'):
            subject, html_body, text_body = email_templates.build_report_status_update(
                ref, username, new_state, report=report, moderation_notes=moderation_notes
            )
            transaction.on_commit(
                lambda: send_email_notification_task.delay(reporter_email, subject, text_body, html_body)
            )

    return report


@transaction.atomic
def file_dispute_for_report(report, disputant, reason, counter_evidence=None, ip_address=None):
    """
    Files a right-of-response dispute against a fraud or misconduct report.
    Transitions report state to 'disputed' and dispatches transactional alert.
    """
    if report.state not in ('published', 'submitted', 'under_review'):
        raise ValueError(f"Disputes cannot be filed on a report in '{report.state}' state.")

    dispute = Dispute.objects.create(
        report=report,
        disputant=disputant,
        reason=reason,
        counter_evidence=counter_evidence,
        status='opened'
    )

    transition_report_state(
        report=report,
        new_state='disputed',
        actor=disputant,
        ip_address=ip_address,
        moderation_notes=f"Dispute #{dispute.id} opened by {disputant.username}"
    )

    reporter_email = getattr(report.reporter, 'email', None)
    if reporter_email:
        ref = report.reference_number
        username = (
            getattr(report.reporter, 'get_full_name', lambda: '')() or
            report.reporter.username
        )
        subject, html_body, text_body = email_templates.build_dispute_opened(ref, username, report=report)
        transaction.on_commit(
            lambda: send_email_notification_task.delay(reporter_email, subject, text_body, html_body)
        )

    return dispute


@transaction.atomic
def resolve_dispute(dispute, outcome, actor, resolution_notes, ip_address=None):
    """
    Adjudicates a dispute.
    If 'accepted': report is transitioned to 'restricted' (quarantined).
    If 'rejected': report is restored to 'published'.
    Dispatches transactional notification to disputant and reporter.
    """
    if outcome not in ['accepted', 'rejected']:
        raise ValueError(f"Invalid dispute resolution outcome '{outcome}'. Must be 'accepted' or 'rejected'.")

    dispute.status = outcome
    dispute.resolution_notes = resolution_notes
    dispute.resolved_at = timezone.now()
    dispute.save(update_fields=['status', 'resolution_notes', 'resolved_at'])

    report = dispute.report
    target_state = 'restricted' if outcome == 'accepted' else 'published'

    transition_report_state(
        report=report,
        new_state=target_state,
        actor=actor,
        ip_address=ip_address,
        moderation_notes=f"Dispute #{dispute.id} {outcome}: {resolution_notes}"
    )

    # Transactional branded HTML notifications to disputant and reporter
    disputant_email = getattr(dispute.disputant, 'email', None)
    if disputant_email:
        ref = report.reference_number
        username = (
            getattr(dispute.disputant, 'get_full_name', lambda: '')() or
            dispute.disputant.username
        )
        subject, html_body, text_body = email_templates.build_dispute_resolved(ref, username, outcome, report=report, notes=resolution_notes)
        transaction.on_commit(
            lambda: send_email_notification_task.delay(disputant_email, subject, text_body, html_body)
        )

    return dispute

