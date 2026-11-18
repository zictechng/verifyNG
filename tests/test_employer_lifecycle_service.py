from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from employer.models import EmployerProfile
from employer.services import BusinessVerificationLifecycleService
from reports.models import AuditLog
from notifications.models import Notification

User = get_user_model()


class EmployerLifecycleServiceTests(TestCase):
    """
    Unit tests for BusinessVerificationLifecycleService (Batch 2).
    Verifies state transitions, audit logging, notification dispatch,
    country-aware authority resolution, and account suspension isolation.
    """

    def setUp(self):
        self.officer = User.objects.create_superuser(
            username='lifecycle_officer',
            email='officer@verifyng.com',
            password='TestOfficerPassword123!',
        )
        self.officer.is_staff = True
        self.officer.save(update_fields=['is_staff'])

        self.employer_user = User.objects.create_user(
            username='dangote_corp',
            email='hr@dangote.ng',
            password='TestPassword123!',
            role='employer',
        )
        self.profile = EmployerProfile.objects.create(
            user=self.employer_user,
            company_name='Dangote Industries Ltd',
            company_rc_number='RC-123456',
            country='NG',
            registration_type='cac',
            verification_status='pending',
            is_verified=False,
        )

        # Non-Nigerian employer (Ghana ORC)
        self.gh_employer_user = User.objects.create_user(
            username='goldkey_gh',
            email='hr@goldkey.com.gh',
            password='TestPassword123!',
            role='employer',
        )
        self.gh_profile = EmployerProfile.objects.create(
            user=self.gh_employer_user,
            company_name='Goldkey Properties Ghana Ltd',
            company_rc_number='CS123452021',
            country='GH',
            registration_type='orc',
            verification_status='pending',
            is_verified=False,
        )

    def test_transition_to_verified(self):
        """Transition to verified updates status, records audit, and dispatches notification."""
        updated = BusinessVerificationLifecycleService.transition_to_verified(
            profile=self.profile,
            officer=self.officer,
            notes='All CAC incorporation checks satisfied.',
        )

        self.assertTrue(updated.is_verified)
        self.assertEqual(updated.verification_status, 'verified')
        self.assertIsNotNone(updated.verified_at)
        self.assertEqual(updated.rejection_reason, '')

        audit = AuditLog.objects.filter(
            action='ADMIN_EMPLOYER_VERIFY',
            performed_by=self.officer,
            target_user=self.employer_user,
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('company'), 'Dangote Industries Ltd')
        self.assertIn('CAC incorporation checks satisfied', audit.details.get('notes', ''))

        notif = Notification.objects.filter(
            recipient=self.employer_user,
            event_type='VERIFICATION_COMPLETED',
        ).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, 'Company CAC Verification Approved')

    def test_transition_to_verified_ghanaian_company(self):
        """Non-Nigerian company verification resolves authority (ORC) in notifications."""
        updated = BusinessVerificationLifecycleService.transition_to_verified(
            profile=self.gh_profile,
            officer=self.officer,
        )

        self.assertTrue(updated.is_verified)
        self.assertEqual(updated.verification_status, 'verified')

        notif = Notification.objects.filter(
            recipient=self.gh_employer_user,
            event_type='VERIFICATION_COMPLETED',
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn('Office of the Registrar of Companies (ORC)', notif.title)
        self.assertIn('Office of the Registrar of Companies (ORC)', notif.body)

    def test_transition_to_rejected(self):
        """Transition to rejected records specific reason and notifies employer."""
        rejection_reason = "Certificate of incorporation scan is illegible."
        updated = BusinessVerificationLifecycleService.transition_to_rejected(
            profile=self.profile,
            reason=rejection_reason,
            officer=self.officer,
        )

        self.assertFalse(updated.is_verified)
        self.assertEqual(updated.verification_status, 'rejected')
        self.assertEqual(updated.rejection_reason, rejection_reason)

        audit = AuditLog.objects.filter(
            action='ADMIN_EMPLOYER_REJECT',
            performed_by=self.officer,
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('reason'), rejection_reason)

        notif = Notification.objects.filter(
            recipient=self.employer_user,
            event_type='VERIFICATION_REJECTED',
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn(rejection_reason, notif.body)

    def test_transition_to_suspended_preserves_account_active(self):
        """
        SAFEGUARD: Suspending corporate verification does NOT lock the user's account.
        profile.user.is_active remains True.
        """
        # Initially verified
        self.profile.is_verified = True
        self.profile.verification_status = 'verified'
        self.profile.save()

        suspension_reason = "Suspected fraudulent company registration in dispute #502."
        updated = BusinessVerificationLifecycleService.transition_to_suspended(
            profile=self.profile,
            reason=suspension_reason,
            officer=self.officer,
        )

        self.assertFalse(updated.is_verified)
        self.assertEqual(updated.verification_status, 'suspended')
        self.assertEqual(updated.rejection_reason, suspension_reason)

        # Account login isolation check
        self.employer_user.refresh_from_db()
        self.assertTrue(self.employer_user.is_active, "User account must remain active when corporate verification is suspended!")

        audit = AuditLog.objects.filter(
            action='ADMIN_EMPLOYER_SUSPENDED',
            performed_by=self.officer,
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('reason'), suspension_reason)

    def test_transition_to_expired(self):
        """Transition to expired records reason and sets status to expired."""
        self.profile.is_verified = True
        self.profile.verification_status = 'verified'
        self.profile.save()

        expiry_reason = "Annual filing certificate validity expired."
        updated = BusinessVerificationLifecycleService.transition_to_expired(
            profile=self.profile,
            reason=expiry_reason,
            officer=self.officer,
        )

        self.assertFalse(updated.is_verified)
        self.assertEqual(updated.verification_status, 'expired')
        self.assertEqual(updated.rejection_reason, expiry_reason)

        audit = AuditLog.objects.filter(
            action='ADMIN_EMPLOYER_EXPIRED',
            performed_by=self.officer,
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('reason'), expiry_reason)

    def test_transition_to_revoked(self):
        """Transition to revoked resets status to unverified and clears verified_at."""
        self.profile.is_verified = True
        self.profile.verification_status = 'verified'
        self.profile.verified_at = timezone.now()
        self.profile.save()

        revocation_reason = "Company struck off by regulatory commission."
        updated = BusinessVerificationLifecycleService.transition_to_revoked(
            profile=self.profile,
            reason=revocation_reason,
            officer=self.officer,
        )

        self.assertFalse(updated.is_verified)
        self.assertEqual(updated.verification_status, 'unverified')
        self.assertIsNone(updated.verified_at)
        self.assertEqual(updated.rejection_reason, revocation_reason)

        audit = AuditLog.objects.filter(
            action='ADMIN_EMPLOYER_UNVERIFY',
            performed_by=self.officer,
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('reason'), revocation_reason)
