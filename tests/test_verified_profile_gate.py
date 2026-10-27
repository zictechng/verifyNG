from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from employer.models import EmployerProfile
from reports.models import FraudReport
from identities.models import SubjectEntity

User = get_user_model()


class VerifiedProfileGateTests(TestCase):
    """
    Exhaustive test suite for platform-wide Verified Profile Gating.
    Ensures:
      - Blocked users cannot perform operations
      - Unverified users can ONLY do public checks, order plans/payments, manage profile/credentials, and auth
      - Unverified users are blocked from active operations (fraud reports, disputes, verifications,
        certificates, staff checks, bulk uploads, monitoring, team invites, misconduct reports)
      - Verified users have full access
    """
    def setUp(self):
        self.client = Client()

        # 1. Active but unverified individual
        self.unverified_user = User.objects.create_user(
            username='unverified_user',
            email='unverified@example.com',
            password='TestPass123!',
            role='individual',
        )

        # 2. Fully verified individual
        self.verified_user = User.objects.create_user(
            username='verified_user',
            email='verified@example.com',
            password='TestPass123!',
            role='individual',
        )
        self.verified_user.identity_verified = True
        self.verified_user.save(update_fields=['identity_verified'])

        # 3. Suspended / blocked user
        self.suspended_user = User.objects.create_user(
            username='suspended_user',
            email='suspended@example.com',
            password='TestPass123!',
            role='individual',
        )
        self.suspended_user.is_suspended = True
        self.suspended_user.save(update_fields=['is_suspended'])

        # 4. Active but unverified employer
        self.unverified_employer = User.objects.create_user(
            username='unverified_corp',
            email='hr@unverified.ng',
            password='TestPass123!',
            role='employer',
        )
        self.unverified_emp_profile = EmployerProfile.objects.create(
            user=self.unverified_employer,
            company_name='Unverified Corp',
            is_verified=False,
            verification_status='unverified',
        )

        # 5. Fully verified employer
        self.verified_employer = User.objects.create_user(
            username='verified_corp',
            email='hr@verified.ng',
            password='TestPass123!',
            role='employer',
        )
        self.verified_emp_profile = EmployerProfile.objects.create(
            user=self.verified_employer,
            company_name='Verified Corp',
            is_verified=True,
            verification_status='verified',
        )

        # Dummy report for dispute testing
        subject = SubjectEntity.objects.create(name='Scam Entity', type='business')
        self.dummy_report = FraudReport.objects.create(
            reporter=self.verified_user,
            target_subject=subject,
            reference_number='FRD-2026-GATE01',
            title='Suspicious Payment',
            allegation='Details of allegation.',
            state='published',
        )

    # ── ALLOWED FOR UNVERIFIED USERS ──────────────────────────────────────────

    def test_unverified_user_can_access_public_check(self):
        """Unverified individual can perform public checks."""
        self.client.force_login(self.unverified_user)
        res = self.client.get(reverse('check'))
        self.assertEqual(res.status_code, 200)

    def test_unverified_user_can_access_plans_and_pricing(self):
        """Unverified individual can view plans and order packages."""
        self.client.force_login(self.unverified_user)
        res = self.client.get(reverse('payments:plans'))
        self.assertEqual(res.status_code, 200)

    def test_unverified_user_can_access_profile_to_submit_id(self):
        """Unverified individual can access their profile page to upload credentials."""
        self.client.force_login(self.unverified_user)
        res = self.client.get(reverse('users:profile'))
        self.assertEqual(res.status_code, 200)

    def test_unverified_employer_can_access_company_profile_to_upload_cac(self):
        """Unverified employer can view company profile to submit CAC registration."""
        self.client.force_login(self.unverified_employer)
        res = self.client.get(reverse('employer:profile'))
        self.assertEqual(res.status_code, 200)

    def test_unverified_employer_can_verify_candidate_certificate(self):
        """
        Unverified employer can access the certificate verify page (200 OK)
        and sees persistent company verification banner. However, any verification
        attempt is locked (COMPANY_VERIFICATION_REQUIRED) and never discloses candidate data.
        """
        self.client.force_login(self.unverified_employer)
        res = self.client.get(reverse('employer:certificate_verify'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Company Profile Verification Required")

        # Attempt verification check
        res_post = self.client.post(reverse('employer:certificate_verify'), {
            'certificate_id': 'VNG-2026-TEST1234',
            'surname': 'Doe',
            'date_of_birth': '1990-01-01',
        })
        self.assertEqual(res_post.status_code, 200)
        self.assertEqual(res_post.context['result']['lookup_state'], 'COMPANY_VERIFICATION_REQUIRED')
        self.assertContains(res_post, "Candidate Clearance Record Locked")

    # ── GATED ACTIVE OPERATIONS FOR INDIVIDUALS ───────────────────────────────

    def test_unverified_user_cannot_create_fraud_report(self):
        """Unverified user cannot create fraud crime reports."""
        self.client.force_login(self.unverified_user)
        res = self.client.get(reverse('reports:create'))

        self.assertEqual(res.status_code, 302)
        self.assertIn('profile', res.url)
        self.assertIn('verification', res.url)

    def test_unverified_user_cannot_request_verification(self):
        """Unverified user cannot request background / identity verifications."""
        self.client.force_login(self.unverified_user)
        res = self.client.get(reverse('verification:create'))
        self.assertEqual(res.status_code, 302)
        self.assertIn('profile', res.url)

    def test_unverified_user_cannot_apply_for_certificate(self):
        """Unverified user cannot apply for a clearance certificate."""
        self.client.force_login(self.unverified_user)
        res = self.client.get(reverse('verification:certificate_apply'))
        self.assertEqual(res.status_code, 302)
        self.assertIn('profile', res.url)

    def test_unverified_user_cannot_file_dispute(self):
        """Unverified user cannot file a right-of-reply dispute."""
        self.client.force_login(self.unverified_user)
        res = self.client.get(reverse('reports:create_dispute', args=[self.dummy_report.reference_number]))
        self.assertEqual(res.status_code, 302)
        self.assertIn('profile', res.url)

    # ── GATED ACTIVE OPERATIONS FOR EMPLOYERS ─────────────────────────────────

    def test_unverified_employer_cannot_create_staff_check(self):
        """Unverified employer cannot initiate a new staff background check."""
        self.client.force_login(self.unverified_employer)
        res = self.client.get(reverse('employer:staff_check_create'))
        self.assertEqual(res.status_code, 302)
        self.assertIn('profile', res.url)

    def test_unverified_employer_cannot_upload_bulk_screening_csv(self):
        """Unverified employer cannot upload bulk screening CSVs."""
        self.client.force_login(self.unverified_employer)
        res = self.client.get(reverse('employer:bulk_upload_create'))
        self.assertEqual(res.status_code, 302)
        self.assertIn('profile', res.url)

    def test_unverified_employer_cannot_invite_team_members(self):
        """Unverified employer cannot invite team members."""
        self.client.force_login(self.unverified_employer)
        res = self.client.post(reverse('employer:team_invite_send'), {'email': 'colleague@corp.ng'})
        self.assertEqual(res.status_code, 302)
        self.assertIn('profile', res.url)

    def test_unverified_employer_cannot_report_staff_misconduct(self):
        """Unverified employer cannot report workplace staff misconduct."""
        self.client.force_login(self.unverified_employer)
        res = self.client.get(reverse('employer:staff_misconduct_report'))
        self.assertEqual(res.status_code, 302)
        self.assertIn('profile', res.url)

    # ── VERIFIED USERS HAVE ACCESS ────────────────────────────────────────────

    def test_verified_user_can_access_active_views(self):
        """Verified user can access verification creation and report creation."""
        self.client.force_login(self.verified_user)
        res_report = self.client.get(reverse('reports:create'))
        self.assertEqual(res_report.status_code, 200)

        res_verif = self.client.get(reverse('verification:create'))
        self.assertEqual(res_verif.status_code, 200)

    def test_verified_employer_can_access_staff_checks(self):
        """Verified employer can access staff screening and bulk screening views."""
        self.client.force_login(self.verified_employer)
        res_check = self.client.get(reverse('employer:staff_check_create'))
        self.assertEqual(res_check.status_code, 200)

        res_bulk = self.client.get(reverse('employer:bulk_upload_create'))
        self.assertEqual(res_bulk.status_code, 200)

    # ── SUSPENDED USER IS BLOCKED ─────────────────────────────────────────────

    def test_suspended_user_is_redirected_to_suspended_page(self):
        """Suspended user is intercepted by middleware and redirected to suspended notice."""
        self.client.force_login(self.suspended_user)
        res = self.client.get(reverse('dashboard:index'))
        self.assertEqual(res.status_code, 302)
        self.assertIn('suspended', res.url)

    # ── PENDING VERIFICATION STATUS AWARENESS ─────────────────────────────────

    def test_pending_employer_shows_under_review_not_submit_document(self):
        """
        When an employer has already submitted CAC documents (status='pending'),
        they receive an 'under compliance review' notice, NOT a request to submit documents.
        """
        pending_emp = User.objects.create_user(
            username='pending_corp',
            email='pending@corp.ng',
            password='TestPass123!',
            role='employer',
        )
        EmployerProfile.objects.create(
            user=pending_emp,
            company_name='Pending Corp Ltd',
            is_verified=False,
            verification_status='pending',
        )
        self.client.force_login(pending_emp)

        # 1. Gated view redirects with 'under review' message
        res_gated = self.client.get(reverse('employer:staff_check_create'), follow=True)
        messages_list = [str(m) for m in res_gated.context['messages']]
        self.assertTrue(any('under compliance review' in m for m in messages_list))
        self.assertFalse(any('Please submit your CAC' in m for m in messages_list))

        # 2. Certificate verify page shows 'Under Compliance Review' banner
        res_cert = self.client.get(reverse('employer:certificate_verify'))
        self.assertContains(res_cert, "Company Verification Under Compliance Review")
        self.assertNotContains(res_cert, "Company Profile Verification Required")

    def test_pending_individual_shows_under_review_message(self):
        """
        When an individual has already submitted government ID (status='pending'),
        they receive an 'under compliance review' message, NOT a request to submit ID.
        """
        pending_user = User.objects.create_user(
            username='pending_citizen',
            email='citizen@example.com',
            password='TestPass123!',
            role='individual',
            id_verification_status='pending',
        )
        self.client.force_login(pending_user)

        res_gated = self.client.get(reverse('reports:create'), follow=True)
        messages_list = [str(m) for m in res_gated.context['messages']]
        self.assertTrue(any('under compliance review' in m for m in messages_list))
        self.assertFalse(any('Please submit your official government ID' in m for m in messages_list))
