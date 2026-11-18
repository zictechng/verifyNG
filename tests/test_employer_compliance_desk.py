import uuid
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from employer.models import EmployerProfile
from core.permissions import has_verified_business_access
from reports.models import AuditLog
from notifications.models import Notification

User = get_user_model()


class EmployerComplianceDeskTests(TestCase):
    """
    Step 6 Comprehensive Tests:
    Pan-African Corporate & Employer Business Verification Desk.
    Verifies:
      1. Country and registry authority context (NG CAC, GH ORC, KE BRS, BJ RCCM, ZA CIPC).
      2. Admin approval via BusinessVerificationLifecycleService.
      3. Admin decline with recorded compliance reason.
      4. Admin suspension of verification with user account isolation (user.is_active remains True).
      5. Admin expiration and revocation of corporate verification.
      6. Employer profile country-aware submission and audit logging.
      7. Backward compatibility for legacy Nigerian accounts.
    """

    def setUp(self):
        self.client = Client()

        # Compliance officer
        self.admin = User.objects.create_superuser(
            username='corp_admin',
            email='admin@corp.verifyng.com',
            password='AdminPass123!',
        )
        self.admin.is_staff = True
        self.admin.save(update_fields=['is_staff'])

        # Nigerian employer
        self.ng_user = User.objects.create_user(
            username='zenith_hr',
            email='hr@zenithbank.ng',
            password='TestPass123!',
            role='employer',
        )
        self.ng_profile = EmployerProfile.objects.create(
            user=self.ng_user,
            company_name='Zenith Bank Plc',
            company_rc_number='RC-123456',
            country='NG',
            registration_type='cac',
            tax_identification_number='12345678-0001',
            verification_status='pending',
            is_verified=False,
        )

        # Ghanaian employer
        self.gh_user = User.objects.create_user(
            username='ecobank_gh',
            email='hr@ecobank.com.gh',
            password='TestPass123!',
            role='employer',
        )
        self.gh_profile = EmployerProfile.objects.create(
            user=self.gh_user,
            company_name='Ecobank Ghana PLC',
            company_rc_number='CS123452021',
            country='GH',
            registration_type='orc',
            tax_identification_number='P0012345678',
            verification_status='pending',
            is_verified=False,
        )

        # South African employer
        self.za_user = User.objects.create_user(
            username='standardbank_za',
            email='hr@standardbank.co.za',
            password='TestPass123!',
            role='employer',
        )
        self.za_profile = EmployerProfile.objects.create(
            user=self.za_user,
            company_name='Standard Bank Group Ltd',
            company_rc_number='2019/123456/07',
            country='ZA',
            registration_type='cipc',
            tax_identification_number='9123456789',
            verification_status='pending',
            is_verified=False,
        )

    def test_admin_employer_detail_context_nigerian_company(self):
        """Verify Nigerian company resolves CAC authority and Nigeria in admin detail."""
        self.client.force_login(self.admin)
        url = reverse('admin_portal:employer_detail', kwargs={'public_id': self.ng_profile.public_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertEqual(ctx['reg_country_code'], 'NG')
        self.assertEqual(ctx['reg_country_name'], 'Nigeria')
        self.assertIn('Corporate Affairs Commission (CAC)', ctx['reg_authority'])

        content = response.content.decode('utf-8')
        self.assertIn('Nigeria (NG)', content)
        self.assertIn('Corporate Affairs Commission (CAC)', content)
        self.assertIn('RC-123456', content)

    def test_admin_employer_detail_context_ghanaian_company(self):
        """Verify Ghanaian company resolves ORC authority and Ghana in admin detail."""
        self.client.force_login(self.admin)
        url = reverse('admin_portal:employer_detail', kwargs={'public_id': self.gh_profile.public_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertEqual(ctx['reg_country_code'], 'GH')
        self.assertEqual(ctx['reg_country_name'], 'Ghana')
        self.assertIn('Office of the Registrar of Companies (ORC)', ctx['reg_authority'])

        content = response.content.decode('utf-8')
        self.assertIn('Ghana (GH)', content)
        self.assertIn('Office of the Registrar of Companies (ORC)', content)

    def test_admin_employer_detail_context_south_african_company(self):
        """Verify South African company resolves CIPC authority and SARS tax spec in admin detail."""
        self.client.force_login(self.admin)
        url = reverse('admin_portal:employer_detail', kwargs={'public_id': self.za_profile.public_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertEqual(ctx['reg_country_code'], 'ZA')
        self.assertEqual(ctx['reg_country_name'], 'South Africa')
        self.assertIn('Companies and Intellectual Property Commission (CIPC)', ctx['reg_authority'])

    def test_admin_approves_business_verification(self):
        """Admin verifies employer: updates status, records audit log, unlocks business access."""
        # Initial state: gated
        verified, _ = has_verified_business_access(self.ng_user)
        self.assertFalse(verified)

        self.client.force_login(self.admin)
        url = reverse('admin_portal:employer_action', kwargs={'public_id': self.ng_profile.public_id})
        response = self.client.post(url, {
            'action': 'verify',
            'verification_notes': 'Certificate of incorporation verified.',
        })
        self.assertEqual(response.status_code, 302)

        self.ng_profile.refresh_from_db()
        self.assertTrue(self.ng_profile.is_verified)
        self.assertEqual(self.ng_profile.verification_status, 'verified')
        self.assertIsNotNone(self.ng_profile.verified_at)

        # Check permission gate immediately unlocks
        verified, _ = has_verified_business_access(self.ng_user)
        self.assertTrue(verified)

        # Check AuditLog
        audit = AuditLog.objects.filter(
            action='ADMIN_EMPLOYER_VERIFY',
            performed_by=self.admin
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('company'), 'Zenith Bank Plc')

    def test_admin_declines_business_verification(self):
        """Admin declines employer verification with reason."""
        self.client.force_login(self.admin)
        url = reverse('admin_portal:employer_action', kwargs={'public_id': self.gh_profile.public_id})
        decline_reason = 'ORC status report missing official stamp and signature.'
        response = self.client.post(url, {
            'action': 'reject',
            'rejection_reason': decline_reason,
        })
        self.assertEqual(response.status_code, 302)

        self.gh_profile.refresh_from_db()
        self.assertFalse(self.gh_profile.is_verified)
        self.assertEqual(self.gh_profile.verification_status, 'rejected')
        self.assertEqual(self.gh_profile.rejection_reason, decline_reason)

        verified, msg = has_verified_business_access(self.gh_user)
        self.assertFalse(verified)
        self.assertIn('declined by compliance', msg)

        audit = AuditLog.objects.filter(
            action='ADMIN_EMPLOYER_REJECT',
            performed_by=self.admin
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('reason'), decline_reason)

    def test_admin_suspends_business_verification_leaves_account_login_active(self):
        """
        SAFEGUARD: Suspending corporate verification locks verification features,
        but leaves user.is_active=True so the employer can still log in and view notices.
        """
        # Initially verified
        self.ng_profile.is_verified = True
        self.ng_profile.verification_status = 'verified'
        self.ng_profile.save()

        self.client.force_login(self.admin)
        url = reverse('admin_portal:employer_action', kwargs={'public_id': self.ng_profile.public_id})
        suspension_reason = 'Regulatory inquiry initiated by CAC under case #812.'
        response = self.client.post(url, {
            'action': 'suspend_verification',
            'suspension_reason': suspension_reason,
        })
        self.assertEqual(response.status_code, 302)

        self.ng_profile.refresh_from_db()
        self.assertFalse(self.ng_profile.is_verified)
        self.assertEqual(self.ng_profile.verification_status, 'suspended')
        self.assertEqual(self.ng_profile.rejection_reason, suspension_reason)

        # Account login isolation check
        self.ng_user.refresh_from_db()
        self.assertTrue(self.ng_user.is_active, "Employer user account must remain active when business verification is suspended!")

        # Verification gate is blocked
        verified, msg = has_verified_business_access(self.ng_user)
        self.assertFalse(verified)
        self.assertIn('suspended by compliance', msg)

        audit = AuditLog.objects.filter(
            action='ADMIN_EMPLOYER_SUSPENDED',
            performed_by=self.admin
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('reason'), suspension_reason)

    def test_admin_marks_business_verification_expired(self):
        """Admin marks verification as expired."""
        self.za_profile.is_verified = True
        self.za_profile.verification_status = 'verified'
        self.za_profile.save()

        self.client.force_login(self.admin)
        url = reverse('admin_portal:employer_action', kwargs={'public_id': self.za_profile.public_id})
        expiry_reason = 'CIPC annual return filing confirmation expired.'
        response = self.client.post(url, {
            'action': 'expire_verification',
            'expiry_reason': expiry_reason,
        })
        self.assertEqual(response.status_code, 302)

        self.za_profile.refresh_from_db()
        self.assertFalse(self.za_profile.is_verified)
        self.assertEqual(self.za_profile.verification_status, 'expired')

        verified, msg = has_verified_business_access(self.za_user)
        self.assertFalse(verified)
        self.assertIn('expired', msg)

    def test_admin_revokes_business_verification(self):
        """Admin revokes verification: status resets to unverified and verified_at is cleared."""
        self.ng_profile.is_verified = True
        self.ng_profile.verification_status = 'verified'
        self.ng_profile.save()

        self.client.force_login(self.admin)
        url = reverse('admin_portal:employer_action', kwargs={'public_id': self.ng_profile.public_id})
        revocation_reason = 'Company officially dissolved.'
        response = self.client.post(url, {
            'action': 'revoke_verification',
            'revocation_reason': revocation_reason,
        })
        self.assertEqual(response.status_code, 302)

        self.ng_profile.refresh_from_db()
        self.assertFalse(self.ng_profile.is_verified)
        self.assertEqual(self.ng_profile.verification_status, 'unverified')
        self.assertIsNone(self.ng_profile.verified_at)

    def test_employer_submits_country_aware_profile_update(self):
        """Employer updates profile with country, registry type, TIN, and document proof."""
        self.client.force_login(self.gh_user)
        url = reverse('employer:profile')
        fake_pdf = SimpleUploadedFile("orc_certificate.pdf", b"%PDF-1.4 test content", content_type="application/pdf")

        response = self.client.post(url, {
            'company_name': 'Ecobank Ghana Limited',
            'country': 'GH',
            'registration_type': 'orc',
            'company_rc_number': 'CS987652022',
            'tax_identification_number': 'P0098765432',
            'industry': 'Financial Services',
            'company_address': '2 Morocco Lane, Accra',
            'contact_phone': '+233302123456',
            'cac_document': fake_pdf,
        })
        self.assertEqual(response.status_code, 302)

        self.gh_profile.refresh_from_db()
        self.assertEqual(self.gh_profile.company_name, 'Ecobank Ghana Limited')
        self.assertEqual(self.gh_profile.country, 'GH')
        self.assertEqual(self.gh_profile.registration_type, 'orc')
        self.assertEqual(self.gh_profile.company_rc_number, 'CS987652022')
        self.assertEqual(self.gh_profile.tax_identification_number, 'P0098765432')
        self.assertEqual(self.gh_profile.verification_status, 'pending')
        self.assertTrue(self.gh_profile.has_cac_document)

        # Check AuditLog for document submission preserving document trail
        audit = AuditLog.objects.filter(
            action='EMPLOYER_BUSINESS_DOCUMENT_SUBMITTED',
            performed_by=self.gh_user
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.details.get('country'), 'GH')
        self.assertEqual(audit.details.get('registration_type'), 'orc')
        self.assertEqual(audit.details.get('company_rc_number'), 'CS987652022')

    def test_legacy_nigerian_employer_backward_compatibility(self):
        """Legacy accounts with country=None default to Nigeria CAC and function cleanly."""
        legacy_user = User.objects.create_user(
            username='legacy_biz',
            email='hr@legacy.ng',
            password='TestPass123!',
            role='employer',
        )
        legacy_profile = EmployerProfile.objects.create(
            user=legacy_user,
            company_name='Legacy Enterprise',
            company_rc_number='BN-12345',
            country=None,  # Legacy account
            registration_type='',
            verification_status='pending',
            is_verified=False,
        )

        self.client.force_login(self.admin)
        url = reverse('admin_portal:employer_detail', kwargs={'public_id': legacy_profile.public_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['reg_country_code'], 'NG')
        self.assertIn('Corporate Affairs Commission (CAC)', response.context['reg_authority'])

        # Approve legacy account
        action_url = reverse('admin_portal:employer_action', kwargs={'public_id': legacy_profile.public_id})
        res_action = self.client.post(action_url, {'action': 'verify'})
        self.assertEqual(res_action.status_code, 302)

        legacy_profile.refresh_from_db()
        self.assertTrue(legacy_profile.is_verified)
        self.assertEqual(legacy_profile.verification_status, 'verified')
