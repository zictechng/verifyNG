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
