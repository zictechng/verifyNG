"""
employer/services.py
Central Business Verification Lifecycle Service for VerifyNG.

Manages all corporate and employer verification state transitions:
  - transition_to_verified: Activates corporate verification (evidence reviewed).
  - transition_to_rejected: Declines submitted registration proof with specific reason.
  - transition_to_suspended: Temporarily suspends business verification without locking account login.
  - transition_to_expired: Marks business documentation as expired.
  - transition_to_revoked: Removes verification status entirely.

Safeguards:
  1. Atomic database state transitions.
  2. Complete compliance officer audit attribution.
  3. Strict account isolation: Suspending corporate verification does NOT deactivate user account.
  4. Pan-African registry awareness (CAC, ORC, BRS, RCCM, CIPC).
  5. Zero false claims: Evidence reviewed, not government registry confirmation.
"""
import logging
from django.db import transaction
from django.utils import timezone
from reports.models import AuditLog
from notifications.services import dispatch_notification
from notifications.email_templates import (
    build_employer_verified,
    build_employer_rejected,
    build_employer_unverified,
)
from users.country_config import get_country_business_config, DEFAULT_COUNTRY

logger = logging.getLogger(__name__)


class BusinessVerificationLifecycleService:
    """
    Central orchestrator for corporate/employer verification state transitions.
    """

    @classmethod
    def _get_registry_authority(cls, profile) -> str:
        """Returns the human-readable registration authority name for the profile's country."""
        country_code = getattr(profile, 'country', None) or DEFAULT_COUNTRY
        config = get_country_business_config(country_code)
        if config:
            reg_type = getattr(profile, 'registration_type', '')
            reg_types = config.get('registration_types', {})
            if reg_type in reg_types:
                return reg_types[reg_type].get('authority', config.get('registration_authority', 'Company Registry'))
            return config.get('registration_authority', 'Corporate Affairs Commission (CAC)')
        return 'Corporate Affairs Commission (CAC)'

    @classmethod
    def _create_audit_log(cls, action, profile, officer=None, request=None, details=None):
        """Creates an audit log entry with officer and request context."""
        extra_kwargs = {}
        if request:
            extra_kwargs['ip_address'] = getattr(request, 'META', {}).get('REMOTE_ADDR')
            extra_kwargs['url_path'] = getattr(request, 'path', '')[:500]
            extra_kwargs['http_method'] = getattr(request, 'method', '')[:10]
            extra_kwargs['user_agent'] = getattr(request, 'META', {}).get('HTTP_USER_AGENT', '')

        merged_details = {
            "employer_profile_id": profile.id,
            "company": profile.company_name,
            "company_name": profile.company_name,
            "country": profile.country or DEFAULT_COUNTRY,
            "registration_type": profile.registration_type or 'cac',
            "company_rc_number": profile.company_rc_number,
            "target_user_id": profile.user_id,
            "target_username": profile.user.username,
        }
        if details:
            merged_details.update(details)

        return AuditLog.objects.create(
            action=action,
            action_type="VERIFICATION",
            performed_by=officer,
            target_user=profile.user,
            details=merged_details,
            **extra_kwargs
        )

    @classmethod
    @transaction.atomic
    def transition_to_verified(cls, profile, officer=None, notes='', request=None):
        """
        Approves employer corporate business documentation (Evidence Reviewed).
        Synchronizes:
          - is_verified = True
          - verification_status = 'verified'
          - verified_at = current timestamp
          - rejection_reason = ''
          - default complimentary service access if unset
        """
        profile.is_verified = True
        profile.verification_status = 'verified'
        profile.verified_at = timezone.now()
        profile.rejection_reason = ''

        if not profile.exempt_services:
            profile.exempt_services = ['check']
        if not profile.billing_exempt_notes:
            profile.billing_exempt_notes = "Verified Company Complimentary Access"

        profile.save(update_fields=[
            'is_verified', 'verification_status', 'verified_at',
            'rejection_reason', 'exempt_services', 'billing_exempt_notes'
        ])

        # Audit Log (action string ADMIN_EMPLOYER_VERIFY maintains backward-compatibility)
        cls._create_audit_log(
            action="ADMIN_EMPLOYER_VERIFY",
            profile=profile,
            officer=officer,
            request=request,
            details={
                "notes": notes,
                "verified_at": profile.verified_at.isoformat(),
            }
        )

        # Country-aware notification
        authority = cls._get_registry_authority(profile)
        is_nigerian = (profile.country or DEFAULT_COUNTRY).upper() == 'NG' or profile.registration_type == 'cac'
        title = 'Company CAC Verification Approved' if is_nigerian else f"Company Verification Approved ({authority})"

        try:
            subject, html_body, text_body = build_employer_verified(
                company_name=profile.company_name,
                username=profile.user.get_full_name() or profile.user.username,
            )
            dispatch_notification(
                recipient=profile.user,
                event_type='VERIFICATION_COMPLETED',
                title=title,
                body=(
                    f"Registration documentation for {profile.company_name} ({authority}) has been reviewed and approved by compliance. "
                    f"Candidate vetting, bulk uploads, and clearance reports are now unlocked."
                ),
                object_reference=f"REG-{profile.company_rc_number or profile.public_id}",
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )
        except Exception as e:
            logger.warning(f"Failed to dispatch employer verification notification: {e}")

        return profile

    @classmethod
    @transaction.atomic
    def transition_to_rejected(cls, profile, reason, officer=None, request=None):
        """
        Declines employer business documentation with compliance reason.
        Synchronizes:
          - is_verified = False
          - verification_status = 'rejected'
          - rejection_reason = reason
        """
        reason_clean = str(reason or '').strip() or 'Business registration document or details could not be validated.'

        profile.is_verified = False
        profile.verification_status = 'rejected'
        profile.rejection_reason = reason_clean
        profile.save(update_fields=['is_verified', 'verification_status', 'rejection_reason'])

        cls._create_audit_log(
            action="ADMIN_EMPLOYER_REJECT",
            profile=profile,
            officer=officer,
            request=request,
            details={"reason": reason_clean}
        )

        authority = cls._get_registry_authority(profile)
        is_nigerian = (profile.country or DEFAULT_COUNTRY).upper() == 'NG' or profile.registration_type == 'cac'
        title = 'Company CAC Verification Declined' if is_nigerian else f"Company Verification Declined ({authority})"

        try:
            subject, html_body, text_body = build_employer_rejected(
                company_name=profile.company_name,
                username=profile.user.get_full_name() or profile.user.username,
                reason=reason_clean,
            )
            dispatch_notification(
                recipient=profile.user,
                event_type='VERIFICATION_REJECTED',
                title=title,
                body=f"Verification for {profile.company_name} could not be approved. Reason: {reason_clean}",
                object_reference=f"REG-{profile.company_rc_number or profile.public_id}",
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )
        except Exception as e:
            logger.warning(f"Failed to dispatch employer rejection notification: {e}")

        return profile

    @classmethod
    @transaction.atomic
    def transition_to_suspended(cls, profile, reason, officer=None, request=None):
        """
        Temporarily suspends corporate verification due to compliance inquiry or dispute.

        SAFEGUARD:
          - Suspends business verification gates (is_verified = False, status = 'suspended').
          - Preserves employer user account (profile.user.is_active remains True).
          - Does NOT lock user account login.
        """
        reason_clean = str(reason or '').strip() or 'Corporate verification temporarily suspended pending compliance review.'

        profile.is_verified = False
        profile.verification_status = 'suspended'
        profile.rejection_reason = reason_clean
        profile.save(update_fields=['is_verified', 'verification_status', 'rejection_reason'])

        cls._create_audit_log(
            action="ADMIN_EMPLOYER_SUSPENDED",
            profile=profile,
            officer=officer,
            request=request,
            details={"reason": reason_clean}
        )

        try:
            dispatch_notification(
                recipient=profile.user,
                event_type='VERIFICATION_REJECTED',
                title='Company Verification Suspended',
                body=f"Corporate verification for {profile.company_name} has been temporarily suspended. Reason: {reason_clean}",
                object_reference=f"REG-{profile.public_id}",
            )
        except Exception as e:
            logger.warning(f"Failed to dispatch employer suspension notification: {e}")

        return profile

    @classmethod
    @transaction.atomic
    def transition_to_expired(cls, profile, reason='', officer=None, request=None):
        """
        Marks employer corporate verification as expired.
        Synchronizes:
          - is_verified = False
          - verification_status = 'expired'
          - rejection_reason = reason
        """
        reason_clean = str(reason or '').strip() or 'Business documentation validity period has expired.'

        profile.is_verified = False
        profile.verification_status = 'expired'
        profile.rejection_reason = reason_clean
        profile.save(update_fields=['is_verified', 'verification_status', 'rejection_reason'])

        cls._create_audit_log(
            action="ADMIN_EMPLOYER_EXPIRED",
            profile=profile,
            officer=officer,
            request=request,
            details={"reason": reason_clean}
        )

        try:
            dispatch_notification(
                recipient=profile.user,
                event_type='VERIFICATION_REJECTED',
                title='Company Verification Expired',
                body=f"Corporate verification documents for {profile.company_name} have expired. Please submit current incorporation documents.",
                object_reference=f"REG-{profile.public_id}",
            )
        except Exception as e:
            logger.warning(f"Failed to dispatch employer expired notification: {e}")

        return profile

    @classmethod
    @transaction.atomic
    def transition_to_revoked(cls, profile, reason='', officer=None, request=None):
        """
        Withdraws / revokes an employer's verified company status entirely.
        Synchronizes:
          - is_verified = False
          - verification_status = 'unverified'
          - verified_at = None
          - rejection_reason = reason
        """
        reason_clean = str(reason or '').strip() or 'Verified company status removed by compliance.'

        profile.is_verified = False
        profile.verification_status = 'unverified'
        profile.verified_at = None
        profile.rejection_reason = reason_clean
        profile.save(update_fields=['is_verified', 'verification_status', 'verified_at', 'rejection_reason'])

        cls._create_audit_log(
            action="ADMIN_EMPLOYER_UNVERIFY",
            profile=profile,
            officer=officer,
            request=request,
            details={"reason": reason_clean}
        )

        try:
            subject, html_body, text_body = build_employer_unverified(
                company_name=profile.company_name,
                username=profile.user.get_full_name() or profile.user.username,
            )
            dispatch_notification(
                recipient=profile.user,
                event_type='VERIFICATION_REJECTED',
                title='Company Verification Status Removed',
                body=f"Verified company status for {profile.company_name} has been removed. Platform candidate checks have been locked.",
                object_reference=f"REG-{profile.public_id}",
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )
        except Exception as e:
            logger.warning(f"Failed to dispatch employer unverified notification: {e}")

        return profile
