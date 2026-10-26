import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from verification.models import VerificationCertificate, CertificateQueryLog
from identities.models import SubjectEntity
from reports.models import AuditLog

User = get_user_model()


class UpdateServiceTests(TestCase):
    def setUp(self):
        self.client = Client(SERVER_NAME='localhost')
        
        # Candidate user
        self.candidate = User.objects.create_user(
            username='abel_uwadia',
            email='abelkenuk@gmail.com',
            first_name='Abel',
            last_name='Uwadia',
            password='testpassword123',
            role='user',
        )

        # Subject entity
        self.subject = SubjectEntity.objects.create(
            name='Abel Uwadia',
            type='person',
        )

        # Active certificate (eligible within 30 days)
        self.cert = VerificationCertificate.objects.create(
            certificate_id='VNG-2026-ABEL1234',
            holder=self.candidate,
            subject=self.subject,
            status='active',
            check_level='enhanced',
            issued_at=timezone.now() - datetime.timedelta(days=5),
            expires_at=timezone.now() + relativedelta(years=3),
            is_monitoring_active=False,
        )

        # Log submission metadata in AuditLog
        AuditLog.objects.create(
            action="TRUSTPASS_APPLICATION_SUBMITTED",
            performed_by=self.candidate,
            details={
                'certificate_id': self.cert.certificate_id,
                'full_name': 'Abel Uwadia',
                'surname': 'Uwadia',
                'date_of_birth': '1990-05-15',
                'email': 'abelkenuk@gmail.com',
                'phone_number': '07884619833',
                'residential_address': '61 Bensham Manor Road, Thornton Heath, CR7 7AE',
            }
        )

    def test_login_page_renders_cleanly(self):
        url = reverse('verification:update_service_login')
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Applicant Update Service')
        self.assertContains(res, 'Certificate Reference ID')

    def test_login_invalid_credentials_fails(self):
        url = reverse('verification:update_service_login')
        res = self.client.post(url, {
            'certificate_id': 'VNG-2026-ABEL1234',
            'surname': 'WrongSurname',
            'date_of_birth': '1990-05-15',
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'does not match our records')
        self.assertIsNone(self.client.session.get('update_service_cert_id'))

    def test_login_when_not_yet_joined_redirects_to_join_wizard(self):
        url = reverse('verification:update_service_login')
        res = self.client.post(url, {
            'certificate_id': 'VNG-2026-ABEL1234',
            'surname': 'Uwadia',
            'date_of_birth': '1990-05-15',
        })
        # Not subscribed yet, but within 30 days -> must redirect to join wizard
        expected_url = f"{reverse('verification:update_service_join')}?cert=VNG-2026-ABEL1234"
        self.assertRedirects(res, expected_url)
        self.assertEqual(self.client.session.get('update_service_cert_id'), 'VNG-2026-ABEL1234')

    def test_login_when_subscribed_redirects_to_portal(self):
        self.cert.is_monitoring_active = True
        self.cert.monitoring_expires_at = timezone.now() + datetime.timedelta(days=365)
        self.cert.save()

        url = reverse('verification:update_service_login')
        res = self.client.post(url, {
            'certificate_id': 'VNG-2026-ABEL1234',
            'surname': 'Uwadia',
            'date_of_birth': '1990-05-15',
        })
        self.assertRedirects(res, reverse('verification:update_service_portal'))

    def test_portal_unauthenticated_without_session_redirects_to_login(self):
        res = self.client.get(reverse('verification:update_service_portal'))
        self.assertRedirects(res, reverse('verification:update_service_login'))

    def test_portal_when_not_subscribed_redirects_to_join(self):
        session = self.client.session
        session['update_service_cert_id'] = self.cert.certificate_id
        session.save()

        res = self.client.get(reverse('verification:update_service_portal'))
        # Cannot view portal until joined
        expected_url = f"{reverse('verification:update_service_join')}?cert=VNG-2026-ABEL1234"
        self.assertRedirects(res, expected_url)

    def test_portal_renders_when_subscribed(self):
        self.cert.is_monitoring_active = True
        self.cert.monitoring_expires_at = timezone.now() + datetime.timedelta(days=365)
        self.cert.save()

        session = self.client.session
        session['update_service_cert_id'] = self.cert.certificate_id
        session.save()

        res = self.client.get(reverse('verification:update_service_portal'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Abel Uwadia')
        self.assertContains(res, 'Contact details')
        self.assertContains(res, 'abelkenuk@gmail.com')
        self.assertContains(res, '61 Bensham Manor Road')
        self.assertContains(res, 'Applications and Certificates')
        self.assertContains(res, 'VNG-2026-ABEL1234')
        self.assertContains(res, 'Enhanced')
        self.assertContains(res, 'Blank, no new information')
        self.assertContains(res, 'View who has carried out a Status check on your Certificates')
        self.assertContains(res, 'Subscription')

    def test_join_wizard_renders_and_prepopulates_details(self):
        session = self.client.session
        session['update_service_cert_id'] = self.cert.certificate_id
        session.save()

        url = f"{reverse('verification:update_service_join')}?cert={self.cert.certificate_id}"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Join Continuous Update Service')
        self.assertContains(res, 'VNG-2026-ABEL1234')
        self.assertContains(res, '07884619833')
        self.assertContains(res, '61 Bensham Manor Road')
        self.assertContains(res, 'Proceed to Pay')

    def test_join_wizard_blocks_when_past_30_days(self):
        # Certificate issued 45 days ago
        self.cert.issued_at = timezone.now() - datetime.timedelta(days=45)
        self.cert.save()

        url = f"{reverse('verification:update_service_join')}?cert={self.cert.certificate_id}"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '30-Day Enrollment Window Closed')
        self.assertContains(res, 'Apply for New Certificate')

    def test_join_wizard_multiple_certificates_prompts_selection(self):
        cert2 = VerificationCertificate.objects.create(
            certificate_id='VNG-2026-ABEL5678',
            holder=self.candidate,
            subject=self.subject,
            status='active',
            check_level='employment',
            issued_at=timezone.now() - datetime.timedelta(days=2),
            expires_at=timezone.now() + relativedelta(years=1),
            is_monitoring_active=False,
        )
        self.client.force_login(self.candidate)

        # Visiting join wizard without ?cert= prompts selection between eligible certs
        res = self.client.get(reverse('verification:update_service_join'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Select Certificate to Enroll')
        self.assertContains(res, 'VNG-2026-ABEL1234')
        self.assertContains(res, 'VNG-2026-ABEL5678')

        # Providing ?cert= explicitly opens that specific certificate's form directly
        res_specific = self.client.get(f"{reverse('verification:update_service_join')}?cert=VNG-2026-ABEL5678")
        self.assertEqual(res_specific.status_code, 200)
        self.assertContains(res_specific, 'VNG-2026-ABEL5678')
        self.assertContains(res_specific, 'Choose different certificate')

    def test_security_isolation_update_session_cannot_access_main_portal(self):
        self.cert.is_monitoring_active = True
        self.cert.save()

        # Authenticate via Update Service
        self.client.post(reverse('verification:update_service_login'), {
            'certificate_id': 'VNG-2026-ABEL1234',
            'surname': 'Uwadia',
            'date_of_birth': '1990-05-15',
        })
        # Attempt to access main dashboard /dashboard/
        res = self.client.get(reverse('dashboard:index'))
        # Must redirect to login because candidate is NOT authenticated into django.contrib.auth
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login/', res.url)

    def test_logout_clears_session(self):
        session = self.client.session
        session['update_service_cert_id'] = self.cert.certificate_id
        session.save()

        res = self.client.get(reverse('verification:update_service_logout'))
        self.assertRedirects(res, reverse('verification:update_service_login'))
        self.assertIsNone(self.client.session.get('update_service_cert_id'))
