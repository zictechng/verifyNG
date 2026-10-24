
# notifications/signals.py
"""
Signal receivers for automatic notification dispatch.

Rules:
- NEVER create AuditLog entries here — that is reports/signals.py's job.
- NEVER set _audit_logged flag here.
- Only observe state transitions; dispatch Celery tasks via services.dispatch_notification.
- Guard all DB lookups with try/except to prevent signal failures from breaking saves.
"""

import logging
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from core.models import SiteConfiguration
from core.email_utils import render_email
from verification.models import VerificationResult
from notifications.services import dispatch_notification

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FraudReport signals
# ---------------------------------------------------------------------------

@receiver(post_save, sender='reports.FraudReport')
def notify_on_report_lifecycle(sender, instance, created, **kwargs):
    """
    Dispatch notifications on fraud report state transitions.
    Triggered after reports/signals.py's fallback audit receiver.
    """
    from notifications import email_templates
    from notifications.services import dispatch_notification

    try:
        reporter = instance.reporter
        if not reporter:
            return

        ref = instance.reference_number

        if created:
            subject, html_body, text_body = email_templates.build_report_submitted(
                ref, reporter.username, report=instance
            )
            dispatch_notification(
                recipient=reporter,
                event_type='REPORT_SUBMITTED',
                title='Fraud report received',
                body=f'Your report {ref} has been received and is queued for review.',
                object_reference=ref,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )
            return

        # State transition notifications
        prev_state = getattr(instance, '_previous_state', None)
        new_state = instance.state

        if not prev_state or prev_state == new_state:
            return

        if getattr(instance, '_notification_dispatched', False):
            return

        notes = getattr(instance, 'moderation_notes', None)
        subject, html_body, text_body = email_templates.build_report_status_update(
            reference_number=ref,
            username=reporter.username,
            new_state=new_state,
            report=instance,
            moderation_notes=notes,
        )

        event_type_map = {
            'published': 'REPORT_PUBLISHED',
            'rejected': 'REPORT_REJECTED',
            'under_review': 'REPORT_UNDER_REVIEW',
            'resolved': 'REPORT_RESOLVED',
            'archived': 'REPORT_ARCHIVED',
            'restricted': 'REPORT_RESTRICTED',
        }
        event_type = event_type_map.get(new_state, 'REPORT_STATUS_UPDATE')
        title_map = {
            'published': 'Your report has been published',
            'rejected': 'Update on your fraud report',
            'under_review': 'Your report is under review',
            'resolved': 'Your report has been resolved',
            'archived': 'Your report has been closed & archived',
            'restricted': 'Report access has been restricted',
        }
        title = title_map.get(new_state, f'Report status updated to {new_state}')

        dispatch_notification(
            recipient=reporter,
            event_type=event_type,
            title=title,
            body=f'Report {ref} status changed to {new_state.replace("_", " ")}.',
            object_reference=ref,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )

    except Exception as exc:
        logger.error("notify_on_report_lifecycle error (pk=%s): %s", instance.pk, exc)


# ---------------------------------------------------------------------------
# Dispute signals
# ---------------------------------------------------------------------------

@receiver(post_save, sender='reports.Dispute')
def notify_on_dispute_lifecycle(sender, instance, created, **kwargs):
    """Dispatch notifications on dispute creation and resolution."""
    from notifications import email_templates
    from notifications.services import dispatch_notification

    try:
        report = instance.report
        reporter = report.reporter
        ref = report.reference_number

        if created:
            if reporter:
                subject, html_body, text_body = email_templates.build_dispute_opened(
                    ref, reporter.username, report=report
                )
                dispatch_notification(
                    recipient=reporter,
                    event_type='DISPUTE_OPENED',
                    title='A dispute has been filed on your report',
                    body=f'A dispute was submitted on report {ref} and is under review.',
                    object_reference=ref,
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                )
            return

        # Resolution transitions
        prev_status = getattr(instance, '_previous_status', None)
        new_status = instance.status

        if not prev_status or prev_status == new_status:
            return

        if new_status in ('accepted', 'rejected'):
            # Notify the disputant
            disputant = instance.disputant
            if disputant:
                subject, html_body, text_body = email_templates.build_dispute_resolved(
                    ref, disputant.username, new_status, report=report, notes=getattr(instance, 'resolution_notes', None)
                )
                dispatch_notification(
                    recipient=disputant,
                    event_type='DISPUTE_RESOLVED',
                    title='Your dispute has been resolved',
                    body=f'Dispute on report {ref} has been {new_status}.',
                    object_reference=ref,
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                )

    except Exception as exc:
        logger.error("notify_on_dispute_lifecycle error (pk=%s): %s", instance.pk, exc)


# ---------------------------------------------------------------------------
# VerificationRequest signals
# ---------------------------------------------------------------------------

@receiver(post_save, sender='verification.VerificationRequest')
def notify_on_verification_lifecycle(sender, instance, created, **kwargs):
    """Dispatch notifications on verification request completion and rejection using branded dynamic templates."""
    if created:
        # No notification on creation — status is 'pending', nothing actionable yet
        return

    try:
        requester = instance.requester
        if not requester:
            return

        ref = instance.reference_number
        prev_status = getattr(instance, '_previous_status', None)
        new_status = instance.status

        if not prev_status or prev_status == new_status:
            return

        config = SiteConfiguration.get_solo()
        site_name = config.site_name
        site_url = config.base_url.rstrip('/')
        user_name = requester.get_full_name() or requester.username
        subject_name = instance.target_subject.name if instance.target_subject else 'Target Subject'
        scope_display = dict(sender.VERIFICATION_TYPES).get(instance.verification_type, instance.verification_type)

        if new_status == 'completed':
            result = getattr(instance, 'result', None)
            outcome = result.outcome if result else 'verified'
            outcome_display = dict(VerificationResult.OUTCOME_CHOICES).get(outcome, 'Verified Genuine')
            summary = result.summary if result else (instance.notes or 'Official verification confirmed and approved.')
            completed_at = (result.verified_at if result else timezone.now()).strftime('%d %B %Y, %I:%M %p')

            subject = f"Verification Completed [{ref}]: {outcome_display} — {site_name}"
            html_body, text_body = render_email('verification_complete', {
                'user_name': user_name,
                'reference_number': ref,
                'subject_name': subject_name,
                'scope_display': scope_display,
                'outcome_display': outcome_display,
                'outcome': outcome,
                'summary': summary,
                'completed_at': completed_at,
                'report_url': f"{site_url}/verification/{ref}/report/",
                'detail_url': f"{site_url}/verification/{ref}/",
            })
            dispatch_notification(
                recipient=requester,
                event_type='VERIFICATION_COMPLETED',
                title=f'Verification Complete: {outcome_display}',
                body=f'Verification request {ref} for {subject_name} has been completed.',
                object_reference=ref,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )

        elif new_status == 'rejected':
            reason_text = instance.notes or "Supporting documentation could not be substantiated against primary records."
            declined_at = timezone.now().strftime('%d %B %Y, %I:%M %p')
            subject = f"Update on Verification Request [{ref}] — {site_name}"
            html_body, text_body = render_email('verification_declined', {
                'user_name': user_name,
                'reference_number': ref,
                'subject_name': subject_name,
                'scope_display': scope_display,
                'reason': reason_text,
                'declined_at': declined_at,
                'detail_url': f"{site_url}/verification/{ref}/",
            })
            dispatch_notification(
                recipient=requester,
                event_type='VERIFICATION_REJECTED',
                title='Update on your verification request',
                body=f'Verification request {ref} for {subject_name} could not be completed.',
                object_reference=ref,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )

    except Exception as exc:
        logger.error("notify_on_verification_lifecycle error (pk=%s): %s", instance.pk, exc)


# Add to the BOTTOM of notifications/signals.py


@receiver(pre_save, sender='reports.FraudReport')
def track_report_status_change(sender, instance, **kwargs):
    """Cache previous report state before save for transition detection."""
    if instance.pk:
        try:
            from reports.models import FraudReport
            prev = FraudReport.objects.filter(pk=instance.pk).values('state').first()
            instance._previous_state = prev['state'] if prev else None
        except Exception:
            instance._previous_state = None
    else:
        instance._previous_state = None


@receiver(pre_save, sender='reports.Dispute')
def track_dispute_status_change(sender, instance, **kwargs):
    """Cache previous dispute status before save for transition detection."""
    if instance.pk:
        try:
            from reports.models import Dispute
            prev = Dispute.objects.filter(pk=instance.pk).values('status').first()
            instance._previous_status = prev['status'] if prev else None
        except Exception:
            instance._previous_status = None
    else:
        instance._previous_status = None


@receiver(pre_save, sender='verification.VerificationRequest')
def track_verification_status_change(sender, instance, **kwargs):
    """Cache previous verification status before save for transition detection."""
    if instance.pk:
        try:
            from verification.models import VerificationRequest
            prev = VerificationRequest.objects.filter(pk=instance.pk).values('status').first()
            instance._previous_status = prev['status'] if prev else None
        except Exception:
            instance._previous_status = None
    else:
        instance._previous_status = None


