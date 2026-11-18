import uuid
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from reports.models import AuditLog
from notifications.models import Notification

User = get_user_model()


class AdminIdentityDeskTests(TestCase):
    """
    Step 5 Compliance & Assurance Desk Tests:
    Verifies the enhanced Individual Identity Comparison Desk:
      1. Country and issuing authority display (Nigeria NIMC, Ghana NIA, unconfigured fallback).
      2. Decoupled assurance level and lifecycle status badges & context.
      3. Approval actions: Basic Verified and Enhanced Verified (with metadata).
      4. Lifecycle actions: Suspend, Expire, Revoke with reasons and officer attribution.
      5. Account suspension isolation (suspending ID does not lock account login).
    """

    def setUp(self):
        self.client = Client()

        # Admin officer
        self.admin = User.objects.create_superuser(
            username='desk_admin',
            email='admin@desk.verifyng.com',
            password='DeskAdminPass123!',
        )
        self.admin.is_staff = True
        self.admin.save(update_fields=['is_staff'])

        # Nigerian applicant
        self.ng_candidate = User.objects.create_user(
            username='tunde_adebayo',
            email='tunde@example.ng',
            password='TestPass123!',
            role='individual',
            country='NG',
            id_type='nin',
            id_number='12345678901',
            id_verification_status='pending',
            assurance_level='unverified',
            identity_verified=False,
        )

        # Ghanaian applicant resident in Nigeria
        self.gh_candidate = User.objects.create_user(
            username='kwame_mensah',
            email='kwame@example.gh',
            password='TestPass123!',
            role='individual',
            country='NG',  # Residence is Nigeria
            id_type='ghana_card',
            id_number='GHA-123456789-0',
            id_verification_status='pending',
            assurance_level='unverified',
            identity_verified=False,
        )

    def test_admin_user_detail_nigerian_applicant_context(self):
        """
        Verify Nigerian NIN applicant displays correct country, authority (NIMC),
        masked number, and independent lifecycle and assurance standings.
        """
        # Record submission audit log with issuing country NG
        AuditLog.objects.create(
            action='USER_IDENTITY_VERIFICATION_SUBMITTED',
            action_type='VERIFICATION',
            performed_by=self.ng_candidate,
            target_user=self.ng_candidate,
            details={
                'issuing_country': 'NG',
                'id_type': 'nin',
                'id_number': '12345678901',
            }
        )

        self.client.force_login(self.admin)
        url = reverse('admin_portal:user_detail', kwargs={'public_id': self.ng_candidate.public_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertEqual(ctx['id_issuing_country_code'], 'NG')
        self.assertEqual(ctx['id_issuing_country_name'], 'Nigeria')
        self.assertEqual(ctx['id_issuing_authority'], 'National Identity Management Commission (NIMC)')
        self.assertEqual(ctx['id_assurance_standing'], 'Awaiting review')

        content = response.content.decode('utf-8')
        self.assertIn('National Identity Management Commission (NIMC)', content)
        self.assertIn('Nigeria', content)
        self.assertIn('Awaiting review', content)
        self.assertIn('Pending Review', content)
        self.assertIn('Approve as Basic Verified', content)
        self.assertIn('Approve as Enhanced Verified', content)

    def test_admin_user_detail_ghanaian_applicant_context(self):
        """
        Verify Ghanaian applicant submitting Ghana Card resolves to Ghana and NIA
        based on document issuing country, regardless of residence country.
        """
        AuditLog.objects.create(
            action='USER_IDENTITY_VERIFICATION_SUBMITTED',
            action_type='VERIFICATION',
            performed_by=self.gh_candidate,
            target_user=self.gh_candidate,
            details={
                'issuing_country': 'GH',
                'id_type': 'ghana_card',
                'id_number': 'GHA-123456789-0',
            }
        )

        self.client.force_login(self.admin)
        url = reverse('admin_portal:user_detail', kwargs={'public_id': self.gh_candidate.public_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertEqual(ctx['id_issuing_country_code'], 'GH')
        self.assertEqual(ctx['id_issuing_country_name'], 'Ghana')
        self.assertEqual(ctx['id_issuing_authority'], 'National Identification Authority (NIA)')

        content = response.content.decode('utf-8')
        self.assertIn('National Identification Authority (NIA)', content)
        self.assertIn('Ghana', content)

    def test_admin_user_detail_unconfigured_authority_fallback(self):
        """
        When document country or authority cannot be determined, it displays
        'Not configured' rather than guessing or defaulting to NIMC.
        """
        self.ng_candidate.id_type = 'unknown_custom_id'
        self.ng_candidate.country = 'ZZ'
        self.ng_candidate.save(update_fields=['id_type', 'country'])

        self.client.force_login(self.admin)
        url = reverse('admin_portal:user_detail', kwargs={'public_id': self.ng_candidate.public_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertEqual(ctx['id_issuing_authority'], 'Not configured')

    def test_admin_approves_basic_identity_verification(self):
        """
        Approve as Basic Verified:
          - Sets assurance_level='basic_verified', id_verification_status='verified', identity_verified=True.
          - Records ADMIN_USER_IDENTITY_VERIFIED with officer attribution.
        """
        self.client.force_login(self.admin)
        url = reverse('admin_portal:user_detail', kwargs={'public_id': self.ng_candidate.public_id})
        response = self.client.post(url, {
            'action': 'verify_identity',
            'admin_notes': 'Document matches facial photo',
        })
        self.assertEqual(response.status_code, 302)

        self.ng_candidate.refresh_from_db()
        self.assertTrue(self.ng_candidate.identity_verified)
        self.assertEqual(self.ng_candidate.id_verification_status, 'verified')
        self.assertEqual(self.ng_candidate.assurance_level, 'basic_verified')

        audit = AuditLog.objects.filter(
            action='ADMIN_USER_IDENTITY_VERIFIED',
            performed_by=self.admin
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('assurance_level'), 'basic_verified')

    def test_admin_approves_enhanced_identity_verification(self):
        """
        Approve as Enhanced Verified:
          - Captures method, provider, reference, and officer notes.
          - Sets assurance_level='enhanced_verified', id_verification_status='verified', identity_verified=True.
        """
        self.client.force_login(self.admin)
        url = reverse('admin_portal:user_detail', kwargs={'public_id': self.gh_candidate.public_id})
        response = self.client.post(url, {
            'action': 'verify_enhanced_identity',
            'enhanced_method': 'Biometric Government Database Check',
            'enhanced_provider': 'Smile ID',
            'enhanced_reference': 'SM-GH-98231',
            'admin_notes': 'NIA biometric match confirmed.',
        })
        self.assertEqual(response.status_code, 302)

        self.gh_candidate.refresh_from_db()
        self.assertTrue(self.gh_candidate.identity_verified)
        self.assertEqual(self.gh_candidate.id_verification_status, 'verified')
        self.assertEqual(self.gh_candidate.assurance_level, 'enhanced_verified')

        audit = AuditLog.objects.filter(
            action='ADMIN_USER_ENHANCED_IDENTITY_VERIFIED',
            performed_by=self.admin
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('assurance_level'), 'enhanced_verified')
        notes_str = audit.details.get('notes', '')
        self.assertIn('Smile ID', notes_str)
        self.assertIn('SM-GH-98231', notes_str)

    def test_admin_suspends_identity_verification(self):
        """
        Suspend verification:
          - Lifecycle status becomes 'suspended', identity_verified becomes False.
          - Historical assurance_level is preserved for enhanced accounts.
          - User account remains active (login is not blocked).
        """
        # Setup verified user
        self.ng_candidate.identity_verified = True
        self.ng_candidate.id_verification_status = 'verified'
        self.ng_candidate.assurance_level = 'enhanced_verified'
        self.ng_candidate.save(update_fields=['identity_verified', 'id_verification_status', 'assurance_level'])

        self.client.force_login(self.admin)
        url = reverse('admin_portal:user_detail', kwargs={'public_id': self.ng_candidate.public_id})
        suspension_reason = 'Duplicate national document suspected in dispute #401'
        response = self.client.post(url, {
            'action': 'suspend_identity',
            'suspension_reason': suspension_reason,
        })
        self.assertEqual(response.status_code, 302)

        self.ng_candidate.refresh_from_db()
        self.assertFalse(self.ng_candidate.identity_verified)
        self.assertEqual(self.ng_candidate.id_verification_status, 'suspended')
        self.assertEqual(self.ng_candidate.assurance_level, 'enhanced_verified')  # Preserved!
        self.assertTrue(self.ng_candidate.is_active)  # Account login not locked!

        audit = AuditLog.objects.filter(
            action='ADMIN_USER_IDENTITY_SUSPENDED',
            performed_by=self.admin
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('reason'), suspension_reason)

        # Check detail page standing
        detail_res = self.client.get(url)
        self.assertEqual(detail_res.context['id_assurance_standing'], 'Previously verified; currently suspended')

    def test_admin_marks_identity_expired(self):
        """
        Mark verification as expired:
          - Lifecycle status becomes 'expired', identity_verified becomes False.
          - Reason recorded in audit log.
        """
        self.ng_candidate.identity_verified = True
        self.ng_candidate.id_verification_status = 'verified'
        self.ng_candidate.assurance_level = 'basic_verified'
        self.ng_candidate.save(update_fields=['identity_verified', 'id_verification_status', 'assurance_level'])

        self.client.force_login(self.admin)
        url = reverse('admin_portal:user_detail', kwargs={'public_id': self.ng_candidate.public_id})
        expiry_reason = 'Document validity expired on 2026-10-31'
        response = self.client.post(url, {
            'action': 'expire_identity',
            'expiry_reason': expiry_reason,
        })
        self.assertEqual(response.status_code, 302)

        self.ng_candidate.refresh_from_db()
        self.assertFalse(self.ng_candidate.identity_verified)
        self.assertEqual(self.ng_candidate.id_verification_status, 'expired')

        audit = AuditLog.objects.filter(
            action='ADMIN_USER_IDENTITY_EXPIRED',
            performed_by=self.admin
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('reason'), expiry_reason)

        detail_res = self.client.get(url)
        self.assertEqual(detail_res.context['id_assurance_standing'], 'Verification has expired')

    def test_admin_revokes_identity_verification(self):
        """
        Revoke verification:
          - Lifecycle status becomes 'unverified', identity_verified becomes False.
          - Assurance level resets to 'unverified'.
          - Revocation reason recorded in audit log.
        """
        self.ng_candidate.identity_verified = True
        self.ng_candidate.id_verification_status = 'verified'
        self.ng_candidate.assurance_level = 'basic_verified'
        self.ng_candidate.save(update_fields=['identity_verified', 'id_verification_status', 'assurance_level'])

        self.client.force_login(self.admin)
        url = reverse('admin_portal:user_detail', kwargs={'public_id': self.ng_candidate.public_id})
        revocation_reason = 'Document reported invalid by issuing authority'
        response = self.client.post(url, {
            'action': 'revoke_identity',
            'revocation_reason': revocation_reason,
        })
        self.assertEqual(response.status_code, 302)

        self.ng_candidate.refresh_from_db()
        self.assertFalse(self.ng_candidate.identity_verified)
        self.assertEqual(self.ng_candidate.id_verification_status, 'unverified')
        self.assertEqual(self.ng_candidate.assurance_level, 'unverified')

        audit = AuditLog.objects.filter(
            action='ADMIN_USER_IDENTITY_REVOKED',
            performed_by=self.admin
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('reason'), revocation_reason)
