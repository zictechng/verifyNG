from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()

class RoleNavigationMatrixTestCase(TestCase):
    def setUp(self):
        self.employer_user = User.objects.create_user(
            username='employer_corp',
            email='hr@corp.ng',
            password='Password123!',
            role='employer',
        )
        self.individual_user = User.objects.create_user(
            username='individual_john',
            email='john@example.com',
            password='Password123!',
            role='individual',
        )

    def test_employer_can_access_certificate_apply_and_my_certificates(self):
        self.client.force_login(self.employer_user)
        # Employer can sponsor certificate
        resp = self.client.get(reverse('verification:certificate_apply'))
        self.assertEqual(resp.status_code, 200)

        # Employer can view sponsored certificates
        resp = self.client.get(reverse('verification:my_certificates'))
        self.assertEqual(resp.status_code, 200)

    def test_employer_blocked_from_update_service(self):
        self.client.force_login(self.employer_user)
        
        # Blocked from joining update service (GET and POST)
        resp = self.client.get(reverse('verification:update_service_join'))
        self.assertRedirects(resp, reverse('employer:certificate_verify'))

        resp = self.client.post(reverse('verification:update_service_join'), {'certificate_id': 'VNG-TEST-001'})
        self.assertRedirects(resp, reverse('employer:certificate_verify'))

        # Blocked from update service login (GET and POST)
        resp = self.client.get(reverse('verification:update_service_login'))
        self.assertRedirects(resp, reverse('employer:certificate_verify'))

        resp = self.client.post(reverse('verification:update_service_login'), {'certificate_id': 'VNG-TEST-001'})
        self.assertRedirects(resp, reverse('employer:certificate_verify'))

        # Blocked from update service portal
        resp = self.client.get(reverse('verification:update_service_portal'))
        self.assertRedirects(resp, reverse('employer:certificate_verify'))

        # Blocked from update service enrollment endpoint
        resp = self.client.get(reverse('verification:update_service_enroll'))
        self.assertRedirects(resp, reverse('employer:certificate_verify'))

        # Blocked from ordering monitoring review or executing monitoring checkout
        resp = self.client.get(reverse('payments:service_checkout_review', args=['monitoring']))
        self.assertRedirects(resp, reverse('employer:certificate_verify'))

        resp = self.client.get(reverse('payments:service_checkout_execute', args=['monitoring']))
        self.assertRedirects(resp, reverse('employer:certificate_verify'))

    def test_employer_can_access_public_check_and_report_fraud(self):
        self.client.force_login(self.employer_user)

        # Public verify
        resp = self.client.get(reverse('check'))
        self.assertEqual(resp.status_code, 200)

        # Report fraud
        resp = self.client.get(reverse('reports:create'))
        self.assertEqual(resp.status_code, 200)

    def test_individual_cannot_access_employer_dashboard(self):
        self.client.force_login(self.individual_user)

        # Individual blocked from employer dashboard
        resp = self.client.get(reverse('employer:dashboard'))
        self.assertEqual(resp.status_code, 403)

    def test_individual_can_access_update_service(self):
        self.client.force_login(self.individual_user)

        # Individual can access update service login
        resp = self.client.get(reverse('verification:update_service_login'))
        self.assertEqual(resp.status_code, 200)

    def test_unapproved_certificate_excluded_from_update_service(self):
        from django.utils import timezone
        from verification.models import VerificationCertificate
        from identities.models import SubjectEntity

        subject = SubjectEntity.objects.create(name='John Doe', type='person')
        
        # 1. Approved/Active certificate
        active_cert = VerificationCertificate.objects.create(
            certificate_id='VNG-2026-ACTIVE01',
            holder=self.individual_user,
            subject=subject,
            check_level='employment',
            status='active',
            issued_at=timezone.now(),
            is_active=True,
        )

        # 2. Unapproved/Pending certificate
        pending_cert = VerificationCertificate.objects.create(
            certificate_id='VNG-2026-PENDING02',
            holder=self.individual_user,
            subject=subject,
            check_level='enhanced',
            status='pending',
            issued_at=None,
            is_active=True,
        )

        self.client.force_login(self.individual_user)

        # Access join update service: should ONLY pick active_cert and NOT offer pending_cert
        resp = self.client.get(reverse('verification:update_service_join'))
        self.assertEqual(resp.status_code, 200)
        # choose_certificate should be False because only 1 certificate is eligible (the active one)
        self.assertFalse(resp.context.get('choose_certificate', False))
        self.assertEqual(resp.context['cert'].certificate_id, active_cert.certificate_id)

        # Even if user forces choose mode ?choose=1, eligible_certs must only have 1 (the active one)
        resp_choose = self.client.get(f"{reverse('verification:update_service_join')}?choose=1")
        # Since eligible_certs length is 1, it directly renders the single active cert
        self.assertEqual(resp_choose.context['cert'].certificate_id, active_cert.certificate_id)

        # Trying to directly target the unapproved/pending certificate redirects with warning
        resp_pending = self.client.get(f"{reverse('verification:update_service_join')}?cert={pending_cert.certificate_id}")
        self.assertRedirects(resp_pending, reverse('verification:my_certificates'))

        # Trying to POST enrollment for unapproved/pending certificate is blocked
        resp_post = self.client.post(reverse('verification:update_service_join'), {
            'certificate_id': pending_cert.certificate_id,
            'email': 'john@example.com',
            'phone_number': '08012345678',
            'residential_address': 'Lagos, Nigeria',
            'declaration': True,
        })
        self.assertRedirects(resp_post, reverse('verification:my_certificates'))
