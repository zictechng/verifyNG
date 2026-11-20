# users/services.py
"""
Authoritative Identity Verification Lifecycle Service for VerifyNG.

Centralizes all identity assurance transitions, lifecycle statuses,
legacy field synchronization, audit logging, and compliance notifications.
Enforces database atomicity and strict state transition integrity.
"""
import logging
from django.db import transaction
from django.utils import timezone
from reports.models import AuditLog

logger = logging.getLogger(__name__)


class IdentityVerificationLifecycleService:
    """
    Central service managing state transitions for user identity verification.
    Guarantees synchronization between assurance_level, id_verification_status,
    and legacy identity_verified Boolean.
    """

    @classmethod
    def get_id_display(cls, user) -> str:
        """Returns clean human-readable name of user's identity document."""
        if hasattr(user, 'get_id_type_display') and user.get_id_type_display():
            return user.get_id_type_display()
        return user.id_type or 'Identity Document'

    @classmethod
    def _create_audit_log(cls, action, user, officer=None, request=None, details=None):
        """Creates an audit log entry with request context if available."""
        extra_kwargs = {}
        if request:
            extra_kwargs['ip_address'] = getattr(request, 'META', {}).get('REMOTE_ADDR')
            extra_kwargs['url_path'] = getattr(request, 'path', '')[:500]
            extra_kwargs['http_method'] = getattr(request, 'method', '')[:10]
            extra_kwargs['user_agent'] = getattr(request, 'META', {}).get('HTTP_USER_AGENT', '')
        return AuditLog.objects.create(
            action=action,
            action_type="VERIFICATION",
            performed_by=officer,
            target_user=user,
            details=details or {},
            **extra_kwargs
        )

    @classmethod
    @transaction.atomic
    def transition_to_basic_verified(cls, user, officer=None, notes='', request=None):
        """
        Transitions user to Basic Identity Evidence Reviewed (Free tier).
        Synchronizes:
          - assurance_level = 'basic_verified' (preserves 'enhanced_verified' if already set)
          - identity_verified = True
          - id_verification_status = 'verified'
          - id_verified_at = current timestamp
          - id_rejection_reason = ''
        """
        if user.assurance_level != 'enhanced_verified':
            user.assurance_level = 'basic_verified'
        user.identity_verified = True
        user.id_verification_status = 'verified'
        user.id_verified_at = timezone.now()
        user.id_rejection_reason = ''
        user.can_publish_reports = True
        user.save(update_fields=[
            'assurance_level', 'identity_verified', 'id_verification_status',
            'id_verified_at', 'id_rejection_reason', 'can_publish_reports'
        ])

        # Audit Log
        cls._create_audit_log(
            action="ADMIN_USER_IDENTITY_VERIFIED",
            user=user,
            officer=officer,
            request=request,
            details={
                "target_user_id": user.id,
                "target_username": user.username,
                "assurance_level": user.assurance_level,
                "id_type": user.id_type,
                "id_number": getattr(user, 'masked_id_number', user.id_number),
                "notes": notes,
            }
        )

        # Dispatch Compliance Notification
        cls._dispatch_notification(
            user=user,
            event_type='VERIFICATION_COMPLETED',
            title='Identity Verification Approved',
            body=(
                f"Your {cls.get_id_display(user)} evidence has been reviewed and accepted by compliance. "
                f"You now hold a Verified Profile badge with access to citizen reporting and trust features."
            )
        )
        return user

    @classmethod
    @transaction.atomic
    def transition_to_enhanced_verified(cls, user, officer=None, notes='', request=None):
        """
        Transitions user to Enhanced Identity Verified (High assurance / Commercial tier).
        Synchronizes:
          - assurance_level = 'enhanced_verified'
          - identity_verified = True
          - id_verification_status = 'verified'
          - id_verified_at = current timestamp
          - id_rejection_reason = ''
        """
        user.assurance_level = 'enhanced_verified'
        user.identity_verified = True
        user.id_verification_status = 'verified'
        user.id_verified_at = timezone.now()
        user.id_rejection_reason = ''
        user.can_publish_reports = True
        user.save(update_fields=[
            'assurance_level', 'identity_verified', 'id_verification_status',
            'id_verified_at', 'id_rejection_reason', 'can_publish_reports'
        ])

        cls._create_audit_log(
            action="ADMIN_USER_ENHANCED_IDENTITY_VERIFIED",
            user=user,
            officer=officer,
            request=request,
            details={
                "target_user_id": user.id,
                "target_username": user.username,
                "assurance_level": "enhanced_verified",
                "id_type": user.id_type,
                "id_number": getattr(user, 'masked_id_number', user.id_number),
                "notes": notes,
            }
        )

        cls._dispatch_notification(
            user=user,
            event_type='VERIFICATION_COMPLETED',
            title='Enhanced Identity Verification Approved',
            body=(
                f"Your {cls.get_id_display(user)} enhanced identity verification has been confirmed. "
                f"You now hold an Enhanced Verified Profile credential with full platform standing."
            )
        )
        return user

    @classmethod
    @transaction.atomic
    def transition_to_rejected(cls, user, reason, officer=None, request=None):
        """
        Rejects submitted identity evidence.
        Synchronizes:
          - identity_verified = False
          - id_verification_status = 'rejected'
          - id_rejection_reason = reason
          - If assurance_level was 'basic_verified', resets to 'unverified'.
          - If assurance_level was 'enhanced_verified', preserves assurance tier, but revokes active Boolean.
        """
        reason_clean = str(reason or '').strip() or 'Submitted document could not be authenticated against compliance standards.'

        if user.assurance_level == 'basic_verified':
            user.assurance_level = 'unverified'

        user.identity_verified = False
        user.id_verification_status = 'rejected'
        user.id_rejection_reason = reason_clean
        # Only reset report publishing if user has no independent Path B alternative verification
        has_path_b = False
        try:
            has_path_b = user.alternative_verification_submissions.filter(status='approved').exists()
        except Exception:
            pass
        if not has_path_b:
            user.can_publish_reports = False

        user.save(update_fields=[
            'assurance_level', 'identity_verified', 'id_verification_status', 'id_rejection_reason', 'can_publish_reports'
        ])

        cls._create_audit_log(
            action="ADMIN_USER_IDENTITY_REJECTED",
            user=user,
            officer=officer,
            request=request,
            details={
                "target_user_id": user.id,
                "target_username": user.username,
                "reason": reason_clean,
            }
        )

        cls._dispatch_notification(
            user=user,
            event_type='VERIFICATION_REJECTED',
            title='Identity Verification Declined',
            body=f"Your identity document review could not be approved. Reason: {reason_clean}",
            rejection_reason=reason_clean
        )
        return user

    @classmethod
    @transaction.atomic
    def transition_to_suspended(cls, user, reason, officer=None, request=None):
        """
        Temporarily suspends an identity verification due to fraud investigation, dispute, or notice.
        Synchronizes:
          - identity_verified = False
          - id_verification_status = 'suspended'
          - id_rejection_reason = reason
          - Preserves assurance_level tier record (e.g. enhanced_verified remains recorded for history).
        """
        reason_clean = str(reason or '').strip() or 'Identity verification temporarily suspended pending compliance inquiry.'

        if user.assurance_level == 'basic_verified':
            user.assurance_level = 'unverified'

        user.identity_verified = False
        user.id_verification_status = 'suspended'
        user.id_rejection_reason = reason_clean
        user.save(update_fields=[
            'assurance_level', 'identity_verified', 'id_verification_status', 'id_rejection_reason'
        ])

        cls._create_audit_log(
            action="ADMIN_USER_IDENTITY_SUSPENDED",
            user=user,
            officer=officer,
            request=request,
            details={
                "target_user_id": user.id,
                "target_username": user.username,
                "reason": reason_clean,
            }
        )

        cls._dispatch_notification(
            user=user,
            event_type='VERIFICATION_REJECTED',
            title='Identity Verification Suspended',
            body=f"Your profile identity verification has been suspended. Reason: {reason_clean}",
            rejection_reason=reason_clean
        )
        return user

    @classmethod
    @transaction.atomic
    def transition_to_expired(cls, user, reason='', officer=None, request=None):
        """
        Marks an identity verification as expired (e.g. document reached expiration date).
        Synchronizes:
          - identity_verified = False
          - id_verification_status = 'expired'
          - If assurance_level was 'basic_verified', resets to 'unverified'.
        """
        reason_clean = str(reason or '').strip() or 'Submitted document validity period has expired.'

        if user.assurance_level == 'basic_verified':
            user.assurance_level = 'unverified'

        user.identity_verified = False
        user.id_verification_status = 'expired'
        user.save(update_fields=['assurance_level', 'identity_verified', 'id_verification_status'])

        cls._create_audit_log(
            action="ADMIN_USER_IDENTITY_EXPIRED",
            user=user,
            officer=officer,
            request=request,
            details={
                "target_user_id": user.id,
                "target_username": user.username,
                "reason": reason_clean,
            }
        )

        cls._dispatch_notification(
            user=user,
            event_type='VERIFICATION_REJECTED',
            title='Identity Verification Expired',
            body="Your identity document on file has reached its validity period. Please submit an updated document to restore verified status."
        )
        return user

    @classmethod
    @transaction.atomic
    def transition_to_revoked(cls, user, reason='', officer=None, request=None):
        """
        Fully revokes identity credentials and returns user to clean unverified state.
        Synchronizes:
          - assurance_level = 'unverified'
          - identity_verified = False
          - id_verification_status = 'unverified'
        """
        reason_clean = str(reason or '').strip() or 'Identity verification credentials withdrawn by compliance.'

        user.assurance_level = 'unverified'
        user.identity_verified = False
        user.id_verification_status = 'unverified'
        user.save(update_fields=['assurance_level', 'identity_verified', 'id_verification_status'])

        cls._create_audit_log(
            action="ADMIN_USER_IDENTITY_REVOKED",
            user=user,
            officer=officer,
            request=request,
            details={
                "target_user_id": user.id,
                "target_username": user.username,
                "reason": reason_clean,
            }
        )

        cls._dispatch_notification(
            user=user,
            event_type='VERIFICATION_REJECTED',
            title='Identity Verification Revoked',
            body="Your verified identity badge has been revoked by platform compliance. Please review your profile credentials."
        )
        return user

    @classmethod
    def _dispatch_notification(cls, user, event_type, title, body, rejection_reason=None):
        """Safely dispatches in-app and email notifications without interrupting transaction."""
        try:
            from notifications.services import dispatch_notification
            from notifications.email_templates import (
                build_identity_verified, build_identity_rejected, build_identity_revoked
            )

            id_display = cls.get_id_display(user)
            username_display = user.get_full_name() or user.username

            if event_type == 'VERIFICATION_COMPLETED':
                subject, html_body, text_body = build_identity_verified(
                    username=username_display,
                    id_type=id_display
                )
            elif title == 'Identity Verification Revoked':
                subject, html_body, text_body = build_identity_revoked(
                    username=username_display
                )
            else:
                subject, html_body, text_body = build_identity_rejected(
                    username=username_display,
                    id_type=id_display,
                    reason=rejection_reason or body
                )

            dispatch_notification(
                recipient=user,
                event_type=event_type,
                title=title,
                body=body,
                object_reference=f"ID-{user.public_id}",
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )
        except Exception as e:
            logger.warning(f"Failed to dispatch verification notification for {user.username}: {e}")
