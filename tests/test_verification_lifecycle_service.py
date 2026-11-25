# tests/test_verification_lifecycle_service.py
"""
Unit and integration test suite for IdentityVerificationLifecycleService
and Admin Compliance Workflow integration.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from users.models import User
from users.services import IdentityVerificationLifecycleService
from reports.models import AuditLog
from notifications.models import Notification


class IdentityVerificationLifecycleServiceTests(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(
            username='compliance_officer',
            email='officer@verifyng.local',
            password='TestPassword123!',
            role='ADMIN'
        )
        self.user = User.objects.create_user(
            username='test_applicant',
            email='applicant@verifyng.local',
            password='TestPassword123!',
            id_type='nin',
            id_number='12345678901'
        )

    def test_transition_to_basic_verified(self):
        """Standard candidate is successfully promoted to basic_verified."""
        updated = IdentityVerificationLifecycleService.transition_to_basic_verified(
            user=self.user,
            officer=self.officer,
            notes='NIN name strictly matches profile registration'
        )
        self.assertEqual(updated.assurance_level, 'basic_verified')
        self.assertTrue(updated.identity_verified)
        self.assertEqual(updated.id_verification_status, 'verified')
        self.assertIsNotNone(updated.id_verified_at)
        self.assertEqual(updated.id_rejection_reason, '')

        # AuditLog assertion
        log = AuditLog.objects.filter(
            action='ADMIN_USER_IDENTITY_VERIFIED',
            target_user=self.user
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.performed_by, self.officer)
        self.assertEqual(log.action_type, 'VERIFICATION')
        self.assertEqual(log.details.get('assurance_level'), 'basic_verified')

        # Notification assertion
        notif = Notification.objects.filter(
            recipient=self.user,
            event_type='VERIFICATION_COMPLETED'
        ).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, 'Profile Approved')

    def test_transition_to_basic_verified_preserves_enhanced(self):
        """Account already holding enhanced_verified is not downgraded to basic."""
        self.user.assurance_level = 'enhanced_verified'
        self.user.identity_verified = False
        self.user.id_verification_status = 'pending'
        self.user.save(update_fields=['assurance_level', 'identity_verified', 'id_verification_status'])

        updated = IdentityVerificationLifecycleService.transition_to_basic_verified(
            user=self.user,
            officer=self.officer
        )
        self.assertEqual(updated.assurance_level, 'enhanced_verified')
        self.assertTrue(updated.identity_verified)
        self.assertEqual(updated.id_verification_status, 'verified')

    def test_transition_to_enhanced_verified(self):
        """Account promoted to enhanced_verified establishes high assurance standing."""
        updated = IdentityVerificationLifecycleService.transition_to_enhanced_verified(
            user=self.user,
            officer=self.officer,
            notes='Authoritative biometric and registry verification completed'
        )
        self.assertEqual(updated.assurance_level, 'enhanced_verified')
        self.assertTrue(updated.identity_verified)
        self.assertEqual(updated.id_verification_status, 'verified')
        self.assertIsNotNone(updated.id_verified_at)

        log = AuditLog.objects.filter(
            action='ADMIN_USER_ENHANCED_IDENTITY_VERIFIED',
            target_user=self.user
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.details.get('assurance_level'), 'enhanced_verified')

        notif = Notification.objects.filter(
            recipient=self.user,
            event_type='VERIFICATION_COMPLETED',
            title='Enhanced Identity Verification Approved'
        ).first()
        self.assertIsNotNone(notif)

    def test_transition_to_rejected_for_basic_account(self):
        """Basic verified account rejected resets assurance level to unverified."""
        self.user.assurance_level = 'basic_verified'
        self.user.identity_verified = True
        self.user.id_verification_status = 'verified'
        self.user.save(update_fields=['assurance_level', 'identity_verified', 'id_verification_status'])

        updated = IdentityVerificationLifecycleService.transition_to_rejected(
            user=self.user,
            reason='Blurry image; name mismatch',
            officer=self.officer
        )
        self.assertEqual(updated.assurance_level, 'unverified')
        self.assertFalse(updated.identity_verified)
        self.assertEqual(updated.id_verification_status, 'rejected')
        self.assertEqual(updated.id_rejection_reason, 'Blurry image; name mismatch')

        log = AuditLog.objects.filter(
            action='ADMIN_USER_IDENTITY_REJECTED',
            target_user=self.user
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.details.get('reason'), 'Blurry image; name mismatch')

        notif = Notification.objects.filter(
            recipient=self.user,
            event_type='VERIFICATION_REJECTED'
        ).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, 'Profile Verification Declined')
        self.assertIn('Blurry image; name mismatch', notif.body)

    def test_transition_to_rejected_preserves_enhanced_assurance_tier(self):
        """Enhanced account rejected preserves historical tier but disables active status."""
        self.user.assurance_level = 'enhanced_verified'
        self.user.identity_verified = True
        self.user.id_verification_status = 'verified'
        self.user.save(update_fields=['assurance_level', 'identity_verified', 'id_verification_status'])

        updated = IdentityVerificationLifecycleService.transition_to_rejected(
            user=self.user,
            reason='PEP sanctions list flag',
            officer=self.officer
        )
        self.assertEqual(updated.assurance_level, 'enhanced_verified')
        self.assertFalse(updated.identity_verified)
        self.assertEqual(updated.id_verification_status, 'rejected')

    def test_transition_to_suspended(self):
        """Suspension preserves enhanced tier while revoking active access."""
        self.user.assurance_level = 'enhanced_verified'
        self.user.identity_verified = True
        self.user.id_verification_status = 'verified'
        self.user.save(update_fields=['assurance_level', 'identity_verified', 'id_verification_status'])

        updated = IdentityVerificationLifecycleService.transition_to_suspended(
            user=self.user,
            reason='Fraud alert received',
            officer=self.officer
        )
        self.assertEqual(updated.assurance_level, 'enhanced_verified')
        self.assertFalse(updated.identity_verified)
        self.assertEqual(updated.id_verification_status, 'suspended')

        log = AuditLog.objects.filter(
            action='ADMIN_USER_IDENTITY_SUSPENDED',
            target_user=self.user
        ).first()
        self.assertIsNotNone(log)

    def test_transition_to_expired(self):
        """Expiration resets basic account to unverified with expired status."""
        self.user.assurance_level = 'basic_verified'
        self.user.identity_verified = True
        self.user.id_verification_status = 'verified'
        self.user.save(update_fields=['assurance_level', 'identity_verified', 'id_verification_status'])

        updated = IdentityVerificationLifecycleService.transition_to_expired(
            user=self.user,
            officer=self.officer
        )
        self.assertEqual(updated.assurance_level, 'unverified')
        self.assertFalse(updated.identity_verified)
        self.assertEqual(updated.id_verification_status, 'expired')

        log = AuditLog.objects.filter(
            action='ADMIN_USER_IDENTITY_EXPIRED',
            target_user=self.user
        ).first()
        self.assertIsNotNone(log)

    def test_transition_to_revoked(self):
        """Revocation unconditionally resets user to unverified state."""
        self.user.assurance_level = 'enhanced_verified'
        self.user.identity_verified = True
        self.user.id_verification_status = 'verified'
        self.user.save(update_fields=['assurance_level', 'identity_verified', 'id_verification_status'])

        updated = IdentityVerificationLifecycleService.transition_to_revoked(
            user=self.user,
            officer=self.officer
        )
        self.assertEqual(updated.assurance_level, 'unverified')
        self.assertFalse(updated.identity_verified)
        self.assertEqual(updated.id_verification_status, 'unverified')

        log = AuditLog.objects.filter(
            action='ADMIN_USER_IDENTITY_REVOKED',
            target_user=self.user
        ).first()
        self.assertIsNotNone(log)

        notif = Notification.objects.filter(
            recipient=self.user,
            event_type='VERIFICATION_REJECTED',
            title='Profile Verification Revoked'
        ).first()
        self.assertIsNotNone(notif)


class AdminComplianceViewsIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username='super_compliance',
            email='super@verifyng.local',
            password='AdminPassword123!',
            role='ADMIN'
        )
        self.applicant = User.objects.create_user(
            username='applicant_jane',
            email='jane@verifyng.local',
            password='TestPassword123!',
            id_type='ghana_card',
            id_number='GHA-00129384-9'
        )
        self.client.force_login(self.admin)
        self.detail_url = reverse('admin_portal:user_detail', kwargs={'public_id': self.applicant.public_id})

    def test_admin_verify_identity_action(self):
        response = self.client.post(self.detail_url, {'action': 'verify_identity'})
        self.assertEqual(response.status_code, 302)
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.assurance_level, 'basic_verified')
        self.assertTrue(self.applicant.identity_verified)
        self.assertEqual(self.applicant.id_verification_status, 'verified')

    def test_admin_verify_enhanced_identity_action(self):
        response = self.client.post(self.detail_url, {'action': 'verify_enhanced_identity'})
        self.assertEqual(response.status_code, 302)
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.assurance_level, 'enhanced_verified')
        self.assertTrue(self.applicant.identity_verified)
        self.assertEqual(self.applicant.id_verification_status, 'verified')

    def test_admin_suspend_identity_action(self):
        self.applicant.assurance_level = 'basic_verified'
        self.applicant.identity_verified = True
        self.applicant.id_verification_status = 'verified'
        self.applicant.save(update_fields=['assurance_level', 'identity_verified', 'id_verification_status'])

        response = self.client.post(self.detail_url, {
            'action': 'suspend_identity',
            'suspension_reason': 'Suspicious transactions linked to identity'
        })
        self.assertEqual(response.status_code, 302)
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.assurance_level, 'unverified')
        self.assertFalse(self.applicant.identity_verified)
        self.assertEqual(self.applicant.id_verification_status, 'suspended')

    def test_admin_expire_identity_action(self):
        self.applicant.assurance_level = 'basic_verified'
        self.applicant.identity_verified = True
        self.applicant.id_verification_status = 'verified'
        self.applicant.save(update_fields=['assurance_level', 'identity_verified', 'id_verification_status'])

        response = self.client.post(self.detail_url, {'action': 'expire_identity'})
        self.assertEqual(response.status_code, 302)
        self.applicant.refresh_from_db()
        self.assertEqual(self.applicant.assurance_level, 'unverified')
        self.assertFalse(self.applicant.identity_verified)
        self.assertEqual(self.applicant.id_verification_status, 'expired')

    def test_admin_reactivate_suspended_identity_action(self):
        """Reactivating a suspended verification restores verified standing with restored notice."""
        self.applicant.id_verification_status = 'suspended'
        self.applicant.identity_verified = False
        self.applicant.save(update_fields=['id_verification_status', 'identity_verified'])

        response = self.client.post(self.detail_url, {
            'action': 'verify_identity',
            'verification_notes': 'Compliance inquiry cleared. Restored.'
        })
        self.assertEqual(response.status_code, 302)
        self.applicant.refresh_from_db()
        self.assertTrue(self.applicant.identity_verified)
        self.assertEqual(self.applicant.id_verification_status, 'verified')

        notif = Notification.objects.filter(
            recipient=self.applicant,
            event_type='VERIFICATION_COMPLETED',
            title='Profile Verification Restored'
        ).first()
        self.assertIsNotNone(notif)
