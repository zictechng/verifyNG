import uuid
import os
from datetime import timedelta
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
                        suspect_location=None, suspect_state=None, suspect_city=None,
                        amount_lost=None):
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

                # Strategy A: Real-time Paystack Account Resolution on form submission
                resolved_account_name = None
                if suspect_bank_account and suspect_bank_name:
                    try:
                        from payments.bank_services import resolve_bank_account
                        resolve_res = resolve_bank_account(suspect_bank_account, suspect_bank_name)
                        if resolve_res.get('success'):
                            resolved_account_name = resolve_res.get('account_name')
                    except Exception as exc:
                        logger.warning("Bank account resolution error during report submission: %s", exc)

                report = FraudReport(
                    reference_number=ref_num,
                    reporter=reporter,
                    target_subject=subject,
                    title=title,
                    allegation=allegation,
                    amount_lost=amount_lost,
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
                            "name": subject_name,
                            "email": suspect_email or "",
                            "phone": suspect_phone or "",
                            "bank_name": suspect_bank_name or "",
                            "bank_account": suspect_bank_account or "",
                            "bank_account_name": resolved_account_name or "",
                            "cac_number": suspect_cac_number or "",
                            "amount_lost": str(amount_lost) if amount_lost is not None else "",
                            "location": suspect_location or "",
                            "state": suspect_state or "",
                            "city": suspect_city or "",
                            "dispute_deadline": (timezone.now() + timedelta(days=7)).strftime('%d %B %Y'),
                            "notice_dispatched": bool(suspect_email or (getattr(subject, 'business_profile', None) and subject.business_profile.contact_email)),
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

                # Dispatch statutory 7-Day Due-Process Notice and In-App Notice to accused party
                target_notice_email = (
                    suspect_email if suspect_email
                    else (getattr(subject, 'business_profile', None) and subject.business_profile.contact_email)
                )
                if target_notice_email:
                    deadline_str = (timezone.now() + timedelta(days=7)).strftime('%d %B %Y')
                    transaction.on_commit(
                        lambda: dispatch_suspect_allegation_notice(report, target_notice_email, deadline_str)
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

    # If dispute or report is resolved or closed, notify merchant store owner and restore seal
    if new_state in ('resolved', 'rejected', 'archived'):
        try:
            from payments.merchant_views import find_merchant_for_report, get_merchant_fraud_reports
            merchant = find_merchant_for_report(report)
            if merchant:
                active_reports = get_merchant_fraud_reports(merchant).exclude(pk=report.pk)
                if not active_reports.exists():
                    if merchant.status in ('disputed', 'under_dispute', 'suspended'):
                        merchant.status = 'active'
                        merchant.save(update_fields=['status', 'updated_at'])

                from notifications.services import dispatch_notification
                from notifications.email_templates import build_merchant_dispute_resolved
                subj, html_b, txt_b = build_merchant_dispute_resolved(
                    store_name=merchant.store_name,
                    username=merchant.user.get_full_name() or merchant.user.username,
                    reference_number=report.reference_number,
                )
                dispatch_notification(
                    recipient=merchant.user,
                    event_type='DISPUTE_RESOLVED',
                    force_email=True,
                    title="Dispute Resolved & Seal Restored 🟢",
                    body=f"Dispute {report.reference_number} regarding '{merchant.store_name}' was resolved. Your Verified Merchant Seal is active.",
                    object_reference=f"report:{report.reference_number}",
                    subject=subj,
                    html_body=html_b,
                    text_body=txt_b,
                )
        except Exception as merch_notif_err:
            logger.warning(f"Failed to dispatch merchant dispute resolved notification: {merch_notif_err}")

    return report


@transaction.atomic
def file_dispute_for_report(report, disputant, reason, counter_evidence=None, ip_address=None):
    """
    Files a right-of-response dispute against a fraud or misconduct report.
    Transitions report state to 'disputed' and dispatches transactional alert.
    Supports subsequent addendums and additional counter-evidence.
    """
    if report.state not in ('published', 'submitted', 'under_review', 'disputed'):
        raise ValueError(f"Disputes cannot be filed on a report in '{report.state}' state.")

    dispute = Dispute.objects.create(
        report=report,
        disputant=disputant,
        reason=reason,
        counter_evidence=counter_evidence,
        status='opened'
    )

    if report.state != 'disputed':
        transition_report_state(
            report=report,
            new_state='disputed',
            actor=disputant,
            ip_address=ip_address,
            moderation_notes=f"Dispute #{dispute.id} opened by {disputant.username}"
        )
    else:
        AuditLog.objects.create(
            report=report,
            action="ADDITIONAL_DEFENSE_SUBMITTED",
            performed_by=disputant,
            ip_address=ip_address,
            details={
                "dispute_id": dispute.id,
                "has_counter_evidence": bool(counter_evidence),
                "reason_preview": reason[:120],
            }
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

    # In-app notification for complainant with Rebuttal Window alert
    if report.reporter:
        try:
            from notifications.services import dispatch_notification
            dispatch_notification(
                recipient=report.reporter,
                event_type='REPORT_SUBMITTED',
                title=f"Defense Filed & Rebuttal Window Open [{report.reference_number}]",
                body=(
                    f"A formal defense has been registered against your report [{report.reference_number}]. "
                    f"Your 3-day right of rebuttal is now open to review the response and submit your final rebuttal."
                ),
                object_reference=report.reference_number,
            )
        except Exception as e:
            logger.warning("Failed to dispatch rebuttal notice to reporter: %s", e)

    return dispute


@transaction.atomic
def submit_complainant_rebuttal(report, reporter, rebuttal_statement, evidence_file=None, ip_address=None):
    """
    Submits a final 1-time rebuttal statement and optional counter-proof
    from the complainant in response to the respondent's defense.
    Enforces equality of arms and closes the pleadings cycle for final adjudication.
    """
    from django.core.exceptions import PermissionDenied
    if report.reporter != reporter:
        raise PermissionDenied("Only the original complainant can submit a rebuttal on this report.")

    if not report.can_submit_rebuttal:
        raise ValueError("A formal rebuttal has already been submitted or this report is not currently disputed.")

    uploaded_ev = None
    if evidence_file:
        uploaded_ev = ReportEvidence.objects.create(
            report=report,
            file=evidence_file,
            file_type='other',
            description="Complainant Final Rebuttal Evidence",
            is_confidential=True,
            storage_provider='local',
        )

    log = AuditLog.objects.create(
        report=report,
        action="COMPLAINANT_REBUTTAL_SUBMITTED",
        performed_by=reporter,
        ip_address=ip_address,
        details={
            "rebuttal_statement": rebuttal_statement,
            "evidence_id": uploaded_ev.id if uploaded_ev else None,
            "evidence_name": uploaded_ev.file.name if uploaded_ev else "",
            "pleadings_closed": True,
        }
    )

    # In-app notification to the accused respondent if registered
    target_user = None
    first_disp = report.disputes.first()
    if first_disp and first_disp.disputant:
        target_user = first_disp.disputant

    if target_user:
        try:
            from notifications.services import dispatch_notification
            dispatch_notification(
                recipient=target_user,
                event_type='REPORT_SUBMITTED',
                title=f"Rebuttal Submitted by Complainant [{report.reference_number}]",
                body=(
                    f"The complainant has submitted their formal rebuttal on report [{report.reference_number}]. "
                    f"All evidentiary submissions are now complete and pending final compliance adjudication."
                ),
                object_reference=report.reference_number,
            )
        except Exception as e:
            logger.warning("Failed to dispatch rebuttal in-app notification: %s", e)

    return log


@transaction.atomic
def issue_moderator_info_request(report, moderator, target_role, message, request_title=None, ip_address=None):
    """
    Issues an interlocutory information request to either the complainant or respondent.
    Records audit log and sends transactional alert.
    """
    if target_role not in ('complainant', 'respondent'):
        raise ValueError("target_role must be 'complainant' or 'respondent'.")

    title = request_title or f"Compliance Information Request regarding {report.reference_number}"

    log = AuditLog.objects.create(
        report=report,
        action="MODERATOR_INFO_REQUEST",
        performed_by=moderator,
        ip_address=ip_address,
        details={
            "target_role": target_role,
            "title": title,
            "message": message,
            "status": "pending",
            "requested_at": timezone.now().isoformat(),
        }
    )

    # Resolve target recipient
    target_user = None
    target_email = None

    if target_role == 'complainant':
        target_user = report.reporter
        target_email = getattr(report.reporter, 'email', None)
    else:
        first_disp = report.disputes.first()
        if first_disp and first_disp.disputant:
            target_user = first_disp.disputant
            target_email = getattr(first_disp.disputant, 'email', None)
        else:
            target_email = report.suspect_email

    if target_user:
        try:
            from notifications.services import dispatch_notification
            dispatch_notification(
                recipient=target_user,
                event_type='REPORT_SUBMITTED',
                title=f"Action Required: Compliance Request for Information [{report.reference_number}]",
                body=f"A compliance moderator has requested clarification or documentation: {message[:120]}...",
                object_reference=report.reference_number,
            )
        except Exception as e:
            logger.warning("Failed to send in-app info request notification: %s", e)

    if target_email:
        from core.site_utils import get_dynamic_base_url
        site_url = get_dynamic_base_url()
        action_url = f"{site_url}/reports/{report.reference_number}/"
        try:
            subject = f"Action Required: Compliance Information Request [{report.reference_number}]"
            body = (
                f"Hello,\n\n"
                f"Our Compliance Moderation Desk is currently reviewing report [{report.reference_number}].\n"
                f"The reviewing officer has requested the following information or documentation:\n\n"
                f"\"{message}\"\n\n"
                f"Please log in to your account and submit the requested response at:\n"
                f"{action_url}\n\n"
                f"Thank you,\n"
                f"VerifyNG Compliance Team"
            )
            transaction.on_commit(
                lambda: send_email_notification_task.delay(target_email, subject, body)
            )
        except Exception as e:
            logger.warning("Failed to queue info request email: %s", e)

    return log


@transaction.atomic
def fulfill_moderator_info_request(report, user, request_id, response_statement, evidence_file=None, ip_address=None):
    """
    Records a user's response to an official moderator information request.
    Marks the request as fulfilled and stores any attached document.
    """
    req_log = report.audit_logs.filter(id=request_id, action="MODERATOR_INFO_REQUEST").first()
    if not req_log:
        raise ValueError("Invalid information request ID.")

    details = req_log.details or {}
    details['status'] = 'fulfilled'
    details['fulfilled_at'] = timezone.now().isoformat()
    details['fulfilled_by_id'] = getattr(user, 'id', None)
    req_log.details = details
    req_log.save(update_fields=['details'])

    uploaded_ev = None
    if evidence_file:
        uploaded_ev = ReportEvidence.objects.create(
            report=report,
            file=evidence_file,
            file_type='other',
            description=f"Response to Compliance Request #{request_id}",
            is_confidential=True,
            storage_provider='local',
        )

    log = AuditLog.objects.create(
        report=report,
        action="INFO_REQUEST_FULFILLED",
        performed_by=user,
        ip_address=ip_address,
        details={
            "request_id": request_id,
            "response_statement": response_statement,
            "evidence_id": uploaded_ev.id if uploaded_ev else None,
            "evidence_name": uploaded_ev.file.name if uploaded_ev else "",
        }
    )
    return log


@transaction.atomic
def resolve_dispute(dispute, outcome, actor, resolution_notes, ip_address=None):
    """
    Adjudicates a dispute.
    If 'resolved': report is transitioned to 'resolved' (case settled; merchant seal restored/active).
    If 'accepted': report is transitioned to 'restricted' (quarantined/removed).
    If 'rejected': report is restored to 'published'.
    Dispatches transactional notification to disputant and reporter.
    """
    if outcome not in ['accepted', 'rejected', 'resolved']:
        raise ValueError(f"Invalid dispute resolution outcome '{outcome}'. Must be 'accepted', 'rejected', or 'resolved'.")

    dispute.status = 'accepted' if outcome == 'resolved' else outcome
    dispute.resolution_notes = resolution_notes
    dispute.resolved_at = timezone.now()
    dispute.save(update_fields=['status', 'resolution_notes', 'resolved_at'])

    report = dispute.report
    if outcome == 'resolved':
        target_state = 'resolved'
    elif outcome == 'accepted':
        target_state = 'restricted'
    else:
        target_state = 'published'

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


def dispatch_suspect_allegation_notice(report, target_email: str, dispute_deadline: str):
    """
    Dispatches the statutory 7-Day Fair Hearing / Right-of-Response Notice
    to the alleged suspect/entity via email and creates an in-app notification if registered.
    """
    try:
        from core.email_utils import get_dynamic_base_url
        from core.models import SiteConfiguration
        config = SiteConfiguration.get_solo()
        site_name = config.site_name or "VerifyNG"
        site_url = get_dynamic_base_url()
        dispute_url = f"{site_url}/reports/{report.reference_number}/dispute/"

        subject = f"Notice of Incident Filing & Right of Response [{report.reference_number}] — {site_name}"
        html_body, text_body = render_email('fraud_allegation_notice', {
            'suspect_name': report.target_subject.name,
            'reference_number': report.reference_number,
            'report_title': report.title,
            'submitted_at': report.created_at.strftime('%d %B %Y, %I:%M %p'),
            'dispute_deadline': dispute_deadline,
            'dispute_url': dispute_url,
        })

        send_email_notification_task.delay(
            recipient_email=target_email,
            subject=subject,
            message_body=text_body,
            html_message=html_body,
        )
        logger.info(
            "Suspect 7-day fair hearing notice dispatched for report=%s to email=%s",
            report.reference_number, target_email[:3] + '***'
        )

        # In-app notification if the suspect/accused is a registered user
        try:
            from users.models import User
            from notifications.services import dispatch_notification

            matched_user = None
            if target_email:
                matched_user = User.objects.filter(email__iexact=target_email.strip()).first()

            if not matched_user and hasattr(report, 'suspect_phone') and report.suspect_phone:
                matched_user = User.objects.filter(phone_number=report.suspect_phone.strip()).first()

            if not matched_user and hasattr(report, 'target_subject') and report.target_subject:
                from verification.models import VerificationCertificate
                cert = VerificationCertificate.objects.filter(subject=report.target_subject, holder__isnull=False).first()
                if cert and cert.holder:
                    matched_user = cert.holder

            if matched_user:
                dispatch_notification(
                    recipient=matched_user,
                    event_type='REPORT_SUBMITTED',
                    title=f"Incident Notice: Allegation Filed [{report.reference_number}]",
                    body=(
                        f"An incident report [{report.reference_number}] has been submitted naming you or your entity. "
                        f"Your statutory 7-day fair-hearing window is open until {dispute_deadline} to review and submit your defense."
                    ),
                    object_reference=report.reference_number,
                )
                logger.info("In-app allegation notice created for user_id=%s, report=%s", matched_user.id, report.reference_number)
        except Exception as notif_err:
            logger.warning("Failed to dispatch in-app notification to accused user: %s", notif_err)

    except Exception as exc:
        logger.warning(
            "Failed to dispatch suspect 7-day fair hearing notice for report=%s: %s",
            report.reference_number, exc
        )


def get_reports_against_user_queryset(user):
    """
    Returns a queryset of all FraudReport instances where the user or their registered entity
    is the alleged subject / accused party.
    """
    if not user or not user.is_authenticated:
        return FraudReport.objects.none()

    from django.db.models import Q
    from reports.models import AuditLog, Dispute

    report_ids = set()

    # 1. Reports where user previously submitted a dispute
    report_ids.update(
        Dispute.objects.filter(disputant=user).values_list('report_id', flat=True)
    )

    # 2. Reports where suspect_context email matches user's email
    if user.email:
        clean_email = user.email.strip().lower()
        sub_logs = AuditLog.objects.filter(
            action="REPORT_SUBMITTED"
        ).filter(
            Q(details__suspect_context__email__iexact=clean_email) |
            Q(details__suspect_context__email__iexact=user.email)
        ).values_list('report_id', flat=True)
        report_ids.update(r_id for r_id in sub_logs if r_id)

    # 3. Reports where suspect_context phone matches user's phone number
    user_phone = getattr(user, 'phone_number', None)
    if user_phone:
        clean_phone = user_phone.strip()
        sub_logs_phone = AuditLog.objects.filter(
            action="REPORT_SUBMITTED",
            details__suspect_context__phone=clean_phone
        ).values_list('report_id', flat=True)
        report_ids.update(r_id for r_id in sub_logs_phone if r_id)

    # 4. Misconduct reports linked to certificates held by user
    try:
        from verification.models import VerificationCertificate
        held_subject_ids = VerificationCertificate.objects.filter(
            holder=user, subject__isnull=False
        ).values_list('subject_id', flat=True)
        if held_subject_ids:
            misconduct_report_ids = FraudReport.objects.filter(
                target_subject_id__in=held_subject_ids
            ).values_list('id', flat=True)
            report_ids.update(misconduct_report_ids)
    except Exception:
        pass

    # 5. Reports associated with user's verified merchant stores (by store name, slug, bank account, phone)
    try:
        from payments.models import MerchantProfile
        from identities.utils import hash_identifier_value
        from identities.models import Identifier
        merchants = MerchantProfile.objects.filter(user=user)
        for merch in merchants:
            merch_hashes = []
            if merch.bank_account:
                merch_hashes.append(hash_identifier_value('account', merch.bank_account))
            if merch.whatsapp_number:
                clean_phone = merch.whatsapp_number.replace('+', '').replace(' ', '').strip()
                merch_hashes.append(hash_identifier_value('phone', clean_phone))
            if merch_hashes:
                matched_subj_ids = Identifier.objects.filter(value_hash__in=merch_hashes).values_list('subject_id', flat=True)
                if matched_subj_ids:
                    merch_rep_ids = FraudReport.objects.filter(target_subject_id__in=matched_subj_ids).values_list('id', flat=True)
                    report_ids.update(merch_rep_ids)
            # Also match by store name in subject or title
            name_reports = FraudReport.objects.filter(
                Q(target_subject__canonical_name__iexact=merch.store_name) |
                Q(title__icontains=merch.store_name)
            ).values_list('id', flat=True)
            report_ids.update(name_reports)
    except Exception:
        pass

    # Exclude reports where user was the reporter
    qs = FraudReport.objects.filter(
        id__in=report_ids
    ).exclude(
        reporter=user
    ).select_related('target_subject').prefetch_related('disputes')

    return qs.order_by('-created_at')


def get_pending_allegations_count_for_user(user) -> int:
    """
    Returns the count of active allegations/reports filed against the user where
    action is required (i.e. user has not yet submitted a right-of-response defense
    and the report is in submitted, under_review, published, or disputed states).
    """
    if not user or not user.is_authenticated:
        return 0

    qs = get_reports_against_user_queryset(user)
    pending_count = 0
    for report in qs.filter(state__in=['submitted', 'under_review', 'published', 'disputed']):
        user_disputes = [d for d in report.disputes.all() if d.disputant_id == user.id]
        if not user_disputes:
            pending_count += 1
        elif any(d.status in ('opened', 'under_review') for d in user_disputes):
            pending_count += 1
    return pending_count


def parse_client_device(user_agent_str: str) -> dict:
    """
    Parses a raw User-Agent header into structured device telemetry:
    device_type (Mobile, Tablet, Desktop, Bot), operating_system, browser, device_brand.
    """
    ua = (user_agent_str or '').lower()
    telemetry = {
        'device_type': 'Desktop',
        'operating_system': 'Unknown OS',
        'browser': 'Unknown Browser',
        'device_brand': 'PC'
    }

    if not ua:
        return telemetry

    if any(b in ua for b in ['bot', 'crawler', 'spider', 'curl', 'wget', 'slurp']):
        telemetry['device_type'] = 'Bot / Crawler'
        telemetry['operating_system'] = 'Automated Agent'
        telemetry['browser'] = 'Bot'
        return telemetry

    if 'ipad' in ua:
        telemetry['device_type'] = 'Tablet'
        telemetry['device_brand'] = 'Apple iPad'
    elif 'iphone' in ua:
        telemetry['device_type'] = 'Mobile'
        telemetry['device_brand'] = 'Apple iPhone'
    elif 'android' in ua:
        if 'mobile' in ua:
            telemetry['device_type'] = 'Mobile'
        else:
            telemetry['device_type'] = 'Tablet'

        if 'samsung' in ua or 'sm-' in ua:
            telemetry['device_brand'] = 'Samsung Galaxy'
        elif 'pixel' in ua:
            telemetry['device_brand'] = 'Google Pixel'
        elif 'redmi' in ua or 'xiaomi' in ua:
            telemetry['device_brand'] = 'Xiaomi / Redmi'
        elif 'huawei' in ua or 'honor' in ua:
            telemetry['device_brand'] = 'Huawei / Honor'
        elif 'transsion' in ua or 'infinix' in ua:
            telemetry['device_brand'] = 'Infinix'
        elif 'tecno' in ua:
            telemetry['device_brand'] = 'Tecno'
        elif 'oppo' in ua:
            telemetry['device_brand'] = 'Oppo'
        else:
            telemetry['device_brand'] = 'Android Device'
    elif 'windows' in ua:
        telemetry['device_type'] = 'Desktop'
        telemetry['device_brand'] = 'Windows PC'
    elif 'macintosh' in ua or 'mac os' in ua:
        telemetry['device_type'] = 'Desktop'
        telemetry['device_brand'] = 'Apple Mac'
    elif 'linux' in ua:
        telemetry['device_type'] = 'Desktop'
        telemetry['device_brand'] = 'Linux Workstation'

    if 'iphone os' in ua or 'ipad; cpu os' in ua:
        try:
            import re
            m = re.search(r'os (\d+[_.]\d+)', ua)
            ver = m.group(1).replace('_', '.') if m else ''
            telemetry['operating_system'] = f"iOS {ver}".strip()
        except Exception:
            telemetry['operating_system'] = 'iOS'
    elif 'android' in ua:
        try:
            import re
            m = re.search(r'android (\d+([.]\d+)?)', ua)
            ver = m.group(1) if m else ''
            telemetry['operating_system'] = f"Android {ver}".strip()
        except Exception:
            telemetry['operating_system'] = 'Android'
    elif 'windows nt 10.0' in ua:
        telemetry['operating_system'] = 'Windows 10/11'
    elif 'windows' in ua:
        telemetry['operating_system'] = 'Windows'
    elif 'mac os x' in ua:
        telemetry['operating_system'] = 'macOS'
    elif 'linux' in ua:
        telemetry['operating_system'] = 'Linux'

    if 'whatsapp' in ua:
        telemetry['browser'] = 'WhatsApp Browser'
    elif 'fban' in ua or 'fbav' in ua:
        telemetry['browser'] = 'Facebook App'
    elif 'instagram' in ua:
        telemetry['browser'] = 'Instagram App'
    elif 'edg/' in ua or 'edge/' in ua:
        telemetry['browser'] = 'Microsoft Edge'
    elif 'opr/' in ua or 'opera' in ua:
        telemetry['browser'] = 'Opera'
    elif 'samsungbrowser' in ua:
        telemetry['browser'] = 'Samsung Internet'
    elif 'chrome' in ua and 'safari' in ua and 'crios' not in ua:
        telemetry['browser'] = 'Google Chrome'
    elif 'crios' in ua:
        telemetry['browser'] = 'Chrome iOS'
    elif 'safari' in ua and 'chrome' not in ua:
        telemetry['browser'] = 'Apple Safari'
    elif 'firefox' in ua or 'fxios' in ua:
        telemetry['browser'] = 'Mozilla Firefox'

    return telemetry


def record_dossier_access(dossier, access_type: str, request, user=None):
    """
    Creates a forensic DossierAccessLog entry and system AuditLog with device telemetry.
    """
    from reports.models import DossierAccessLog, AuditLog
    from core.rate_limiting import get_client_ip
    from django.utils import timezone

    ip = get_client_ip(request) if request else None
    ua = request.META.get('HTTP_USER_AGENT', '') if request else ''
    referer = (request.META.get('HTTP_REFERER', '') or '')[:255] if request else ''
    telemetry = parse_client_device(ua)

    log_user = user
    if not log_user and request and getattr(request, 'user', None) and request.user.is_authenticated:
        log_user = request.user

    access_log = DossierAccessLog.objects.create(
        dossier=dossier,
        access_type=access_type,
        ip_address=ip,
        user_agent=ua,
        device_type=telemetry['device_type'],
        operating_system=telemetry['operating_system'],
        browser=telemetry['browser'],
        device_brand=telemetry['device_brand'],
        referer=referer,
        accessed_by=log_user
    )

    if access_type == 'qr_scan':
        dossier.scan_count = (dossier.scan_count or 0) + 1
        dossier.last_scanned_at = timezone.now()
        dossier.save(update_fields=['scan_count', 'last_scanned_at'])

    action_map = {
        'qr_scan': 'DOSSIER_QR_SCANNED',
        'pdf_download': 'DOSSIER_PRINTED_OR_DOWNLOADED',
        'dossier_order': 'DOSSIER_ORDERED',
    }
    AuditLog.objects.create(
        report=dossier.report,
        action=action_map.get(access_type, 'DOSSIER_ACCESSED'),
        performed_by=log_user,
        ip_address=ip,
        details={
            'tracking_id': dossier.tracking_id,
            'access_type': access_type,
            'device_type': telemetry['device_type'],
            'device_brand': telemetry['device_brand'],
            'operating_system': telemetry['operating_system'],
            'browser': telemetry['browser'],
            'scan_count': dossier.scan_count,
        }
    )
    return access_log
