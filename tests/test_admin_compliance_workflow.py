import uuid
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from employer.models import EmployerProfile
from core.permissions import is_profile_verified, is_account_blocked
from reports.models import FraudReport, AuditLog
from notifications.models import Notification

User = get_user_model()


class AdminComplianceWorkflowTests(TestCase):
    """
    Batch 1 Compliance Tests:
    Admin compliance approval and rejection workflows for:
      1. Individual Government Identity Verification (NIN, BVN, PVC, Passport).
      2. Employer Corporate Verification (CAC Registration & Incorporation Documents).
    Verifies state transitions, audit logging, and instantaneous gating responses.
    """

    def setUp(self):
        self.client = Client()

        # 1. Superadmin / Staff User
        self.admin = User.objects.create_superuser(
            username='compliance_admin',
            email='admin@verifyng.com',
            password='AdminPassword123!',
        )
        self.admin.is_staff = True
        self.admin.save(update_fields=['is_staff'])

        # 2. Individual User with Pending ID Submission
        self.candidate = User.objects.create_user(
            username='amina_lawal',
            email='amina@example.com',
            password='TestPass123!',
            role='individual',
            id_type='nin',
            id_number='12345678901',
            id_verification_status='pending',
            identity_verified=False,
        )

        # 3. Employer Account with Pending CAC Document Submission
        self.employer_user = User.objects.create_user(
            username='apex_hr',
            email='hr@apexholdings.ng',
            password='TestPass123!',
            role='employer',
        )
        self.employer_profile = EmployerProfile.objects.create(
            user=self.employer_user,
            company_name='Apex Holdings Ltd',
            company_rc_number='RC-987654',
            verification_status='pending',
            is_verified=False,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 1. INDIVIDUAL IDENTITY APPROVAL & REJECTION WORKFLOW
    # ─────────────────────────────────────────────────────────────────────────

    def test_admin_approves_individual_identity_verification(self):
        """
        Admin approves candidate's government ID:
          - Sets identity_verified=True and id_verification_status='verified'.
          - Sets id_verified_at timestamp and clears rejection reason.
          - Creates ADMIN_USER_IDENTITY_VERIFIED audit log.
          - Instantly unlocks report creation and verification request gates.
        """
        # Step 1: Confirm candidate is initially gated
        verified, msg = is_profile_verified(self.candidate)
        self.assertFalse(verified)
        self.assertIn("under compliance review", msg)

        self.client.force_login(self.candidate)
        gate_res = self.client.get(reverse('reports:create'))
        self.assertEqual(gate_res.status_code, 302)
        self.assertIn('/profile/', gate_res.url)

        # Step 2: Admin approves identity via AdminUserDetailView
        self.client.force_login(self.admin)
        url = reverse('admin_portal:user_detail', kwargs={'public_id': self.candidate.public_id})
        response = self.client.post(url, {'action': 'verify_identity'})

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, url)

        # Step 3: Verify DB state updates
        self.candidate.refresh_from_db()
        self.assertTrue(self.candidate.identity_verified)
        self.assertEqual(self.candidate.id_verification_status, 'verified')
        self.assertIsNotNone(self.candidate.id_verified_at)
        self.assertEqual(self.candidate.id_rejection_reason, '')

        # Step 4: Verify AuditLog record
        audit = AuditLog.objects.filter(
            action="ADMIN_USER_IDENTITY_VERIFIED",
            performed_by=self.admin
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('target_username'), self.candidate.username)

        # Step 4b: Verify In-App Notification
        notif = Notification.objects.filter(
            recipient=self.candidate,
            event_type="VERIFICATION_COMPLETED",
        ).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, 'Identity Verification Approved')

        # Step 5: Verify gates immediately unlock for candidate
        verified, _ = is_profile_verified(self.candidate)
        self.assertTrue(verified)

        self.client.force_login(self.candidate)
        res_report = self.client.get(reverse('reports:create'))
        self.assertEqual(res_report.status_code, 200)

        res_verif = self.client.get(reverse('verification:create'))
        self.assertEqual(res_verif.status_code, 200)

    def test_admin_declines_individual_identity_verification(self):
        """
        Admin rejects candidate's government ID:
          - Sets identity_verified=False and id_verification_status='rejected'.
          - Records compliance rejection reason.
          - Creates ADMIN_USER_IDENTITY_REJECTED audit log.
          - Profile gate remains locked, displaying specific rejection reason.
        """
        self.client.force_login(self.admin)
        url = reverse('admin_portal:user_detail', kwargs={'public_id': self.candidate.public_id})
        rejection_reason = "NIN name does not match full legal name on file."

        response = self.client.post(url, {
            'action': 'reject_identity',
            'rejection_reason': rejection_reason,
        })
        self.assertEqual(response.status_code, 302)

        # Verify DB state
        self.candidate.refresh_from_db()
        self.assertFalse(self.candidate.identity_verified)
        self.assertEqual(self.candidate.id_verification_status, 'rejected')
        self.assertEqual(self.candidate.id_rejection_reason, rejection_reason)

        # Verify AuditLog record
        audit = AuditLog.objects.filter(
            action="ADMIN_USER_IDENTITY_REJECTED",
            performed_by=self.admin
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('reason'), rejection_reason)

        # Verify In-App Notification
        notif = Notification.objects.filter(
            recipient=self.candidate,
            event_type="VERIFICATION_REJECTED",
        ).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, 'Identity Verification Declined')
        self.assertIn(rejection_reason, notif.body)

        # Verify profile gate returns rejected status message
        verified, msg = is_profile_verified(self.candidate)
        self.assertFalse(verified)
        self.assertIn("declined by compliance", msg)

        # Verify gated view redirects to profile
        self.client.force_login(self.candidate)
        res = self.client.get(reverse('reports:create'))
        self.assertEqual(res.status_code, 302)
        self.assertIn('/profile/', res.url)

    def test_admin_revokes_individual_identity_verification(self):
        """
        Admin revokes an active identity verification badge:
          - Status reverts to 'unverified' and identity_verified=False.
          - Profile gate re-locks immediately.
        """
        # Start with verified user
        self.candidate.identity_verified = True
        self.candidate.id_verification_status = 'verified'
        self.candidate.save(update_fields=['identity_verified', 'id_verification_status'])

        self.client.force_login(self.admin)
        url = reverse('admin_portal:user_detail', kwargs={'public_id': self.candidate.public_id})
        response = self.client.post(url, {'action': 'revoke_identity'})
        self.assertEqual(response.status_code, 302)

        self.candidate.refresh_from_db()
        self.assertFalse(self.candidate.identity_verified)
        self.assertEqual(self.candidate.id_verification_status, 'unverified')

        # Verify In-App Notification
        notif = Notification.objects.filter(
            recipient=self.candidate,
            event_type="VERIFICATION_REJECTED",
        ).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, 'Identity Verification Revoked')

        verified, msg = is_profile_verified(self.candidate)
        self.assertFalse(verified)
        self.assertIn("Identity verification required", msg)

    # ─────────────────────────────────────────────────────────────────────────
    # 2. EMPLOYER CAC APPROVAL & REJECTION WORKFLOW
    # ─────────────────────────────────────────────────────────────────────────

    def test_admin_approves_employer_cac_verification(self):
        """
        Admin approves employer's CAC documentation:
          - Sets is_verified=True and verification_status='verified'.
          - Records verified_at timestamp and clears rejection reason.
          - Creates ADMIN_EMPLOYER_VERIFY audit log.
          - Instantly unlocks staff check creation, bulk uploads, and certificate verification.
        """
        # Step 1: Confirm employer is initially gated
        verified, msg = is_profile_verified(self.employer_user)
        self.assertFalse(verified)
        self.assertIn("under compliance review", msg)

        self.client.force_login(self.employer_user)
        gate_res = self.client.get(reverse('employer:staff_check_create'))
        self.assertEqual(gate_res.status_code, 302)
        self.assertIn('/profile/', gate_res.url)

        # Step 2: Admin approves CAC via AdminEmployerActionView
        self.client.force_login(self.admin)
        url = reverse('admin_portal:employer_action', kwargs={'public_id': self.employer_user.public_id})
        response = self.client.post(url, {'action': 'verify'})

        self.assertEqual(response.status_code, 302)

        # Step 3: Verify DB state updates
        self.employer_profile.refresh_from_db()
        self.assertTrue(self.employer_profile.is_verified)
        self.assertEqual(self.employer_profile.verification_status, 'verified')
        self.assertIsNotNone(self.employer_profile.verified_at)
        self.assertEqual(self.employer_profile.rejection_reason, '')

        # Step 4: Verify AuditLog record
        audit = AuditLog.objects.filter(
            action="ADMIN_EMPLOYER_VERIFY",
            performed_by=self.admin
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('company'), self.employer_profile.company_name)

        # Step 4b: Verify In-App Notification
        notif = Notification.objects.filter(
            recipient=self.employer_user,
            event_type="VERIFICATION_COMPLETED",
        ).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, 'Company CAC Verification Approved')

        # Step 5: Verify gates immediately unlock for employer
        verified, _ = is_profile_verified(self.employer_user)
        self.assertTrue(verified)

        self.client.force_login(self.employer_user)
        res_staff = self.client.get(reverse('employer:staff_check_create'))
        self.assertEqual(res_staff.status_code, 200)

        res_bulk = self.client.get(reverse('employer:bulk_upload_create'))
        self.assertEqual(res_bulk.status_code, 200)

        res_cert = self.client.get(reverse('employer:certificate_verify'))
        self.assertEqual(res_cert.status_code, 200)
        self.assertNotContains(res_cert, 'COMPANY_VERIFICATION_REQUIRED')

    def test_admin_declines_employer_cac_verification(self):
        """
        Admin rejects employer CAC proof:
          - Sets is_verified=False and verification_status='rejected'.
          - Records rejection reason.
          - Creates ADMIN_EMPLOYER_REJECT audit log.
          - Employer actions remain locked with explicit declined message.
        """
        self.client.force_login(self.admin)
        url = reverse('admin_portal:employer_action', kwargs={'public_id': self.employer_user.public_id})
        decline_reason = "CAC registration certificate image is illegible; RC number mismatch."

        response = self.client.post(url, {
            'action': 'reject',
            'rejection_reason': decline_reason,
        })
        self.assertEqual(response.status_code, 302)

        # Verify DB state
        self.employer_profile.refresh_from_db()
        self.assertFalse(self.employer_profile.is_verified)
        self.assertEqual(self.employer_profile.verification_status, 'rejected')
        self.assertEqual(self.employer_profile.rejection_reason, decline_reason)

        # Verify AuditLog record
        audit = AuditLog.objects.filter(
            action="ADMIN_EMPLOYER_REJECT",
            performed_by=self.admin
        ).first()
        self.assertIsNotNone(audit)

        # Verify In-App Notification
        notif = Notification.objects.filter(
            recipient=self.employer_user,
            event_type="VERIFICATION_REJECTED",
        ).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, 'Company CAC Verification Declined')
        self.assertIn(decline_reason, notif.body)

        # Verify profile gate returns rejected status message
        verified, msg = is_profile_verified(self.employer_user)
        self.assertFalse(verified)
        self.assertIn("declined by compliance", msg)

        # Verify employer certificate verify displays locked banner and reason
        self.client.force_login(self.employer_user)
        res = self.client.get(reverse('employer:certificate_verify'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Company CAC Verification Declined')
        self.assertContains(res, decline_reason)

    def test_admin_unverifies_employer(self):
        """
        Admin removes verified status from an employer:
          - Status reverts to 'unverified' and is_verified=False.
          - Platform gates re-lock immediately.
        """
        # Start with verified employer
        self.employer_profile.is_verified = True
        self.employer_profile.verification_status = 'verified'
        self.employer_profile.save(update_fields=['is_verified', 'verification_status'])

        self.client.force_login(self.admin)
        url = reverse('admin_portal:employer_action', kwargs={'public_id': self.employer_user.public_id})
        response = self.client.post(url, {'action': 'unverify'})
        self.assertEqual(response.status_code, 302)

        self.employer_profile.refresh_from_db()
        self.assertFalse(self.employer_profile.is_verified)
        self.assertEqual(self.employer_profile.verification_status, 'unverified')

        # Verify In-App Notification
        notif = Notification.objects.filter(
            recipient=self.employer_user,
            event_type="VERIFICATION_REJECTED",
        ).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, 'Company Verification Status Removed')

        verified, msg = is_profile_verified(self.employer_user)
        self.assertFalse(verified)
        self.assertIn("Company verification required", msg)

    def test_admin_suspends_and_reinstates_employer_account(self):
        """
        Admin suspends and reinstates an employer account:
          - 'suspend' sets user.is_active=False.
          - is_account_blocked returns True.
          - 'reinstate' sets user.is_active=True.
        """
        self.client.force_login(self.admin)
        url = reverse('admin_portal:employer_action', kwargs={'public_id': self.employer_user.public_id})

        # Suspend
        res_suspend = self.client.post(url, {'action': 'suspend'})
        self.assertEqual(res_suspend.status_code, 302)

        self.employer_user.refresh_from_db()
        self.assertFalse(self.employer_user.is_active)
        self.assertTrue(is_account_blocked(self.employer_user))

        # Reinstate
        res_reinstate = self.client.post(url, {'action': 'reinstate'})
        self.assertEqual(res_reinstate.status_code, 302)

        self.employer_user.refresh_from_db()
        self.assertTrue(self.employer_user.is_active)
        self.assertFalse(is_account_blocked(self.employer_user))

    def test_unauthorized_user_cannot_trigger_compliance_actions(self):
        """
        Non-admin users cannot perform identity or employer compliance actions.
        """
        self.client.force_login(self.candidate)
        user_action_url = reverse('admin_portal:user_detail', kwargs={'public_id': self.candidate.public_id})
        res1 = self.client.post(user_action_url, {'action': 'verify_identity'})
        self.assertIn(res1.status_code, (302, 403))

        emp_action_url = reverse('admin_portal:employer_action', kwargs={'public_id': self.employer_user.public_id})
        res2 = self.client.post(emp_action_url, {'action': 'verify'})
        self.assertIn(res2.status_code, (302, 403))
