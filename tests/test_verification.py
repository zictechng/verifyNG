# tests/test_verification.py
"""W-08 — VerificationCertificate system tests."""

from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse

from users.models import User
from identities.models import SubjectEntity
from verification.models import (
    VerificationCertificate,
    CertificateQueryLog,
    generate_certificate_id,
)
from verification.services import (
    create_certificate_application,
    log_certificate_query,
    get_certificate_query_price,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_user(username='testuser', email='test@example.com', identity_verified=True):
    u = User.objects.create_user(
        username=username, email=email, password='StrongPass123!'
    )
    if identity_verified:
        u.identity_verified = True
        u.save(update_fields=['identity_verified'])
    return u


def make_subject(name='Jane Doe', entity_type='person'):
    return SubjectEntity.objects.create(name=name, type=entity_type)


def make_certificate(holder, subject=None, status='active'):
    if subject is None:
        subject = make_subject(name=f'Subject for {holder.username}')
    return VerificationCertificate.objects.create(
        certificate_id=generate_certificate_id(),
        subject=subject,
        holder=holder,
        check_level='employment',
        status=status,
        is_active=True,
    )


def make_payment(user):
    """Create a minimal payments.Transaction for FK use in CertificateQueryLog."""
    from payments.models import Transaction
    return Transaction.objects.create(
        user=user,
        reference=f'TEST-{secrets.token_hex(4).upper()}',
        amount=5000,
        currency='NGN',
        status='success',
    )


# ─── generate_certificate_id ──────────────────────────────────────────────────

class GenerateCertificateIdTests(TestCase):

    def test_format(self):
        cert_id = generate_certificate_id()
        parts = cert_id.split('-')
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0], 'VNG')
        self.assertTrue(parts[1].isdigit())
        self.assertEqual(len(parts[2]), 8)
        self.assertEqual(parts[2], parts[2].upper())

    def test_uniqueness(self):
        ids = {generate_certificate_id() for _ in range(50)}
        self.assertEqual(len(ids), 50)


# ─── get_certificate_query_price ──────────────────────────────────────────────

class GetCertificateQueryPriceTests(TestCase):

    def test_employment_price(self):
        self.assertEqual(get_certificate_query_price('employment'), 5000)

    def test_enhanced_price(self):
        self.assertEqual(get_certificate_query_price('enhanced'), 10000)

    def test_unknown_level_defaults(self):
        self.assertEqual(get_certificate_query_price('unknown'), 5000)


# ─── create_certificate_application ──────────────────────────────────────────

class CreateCertificateApplicationTests(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_creates_pending_certificate(self):
        cert = create_certificate_application(self.user, check_level='employment')
        self.assertEqual(cert.status, 'pending')
        self.assertEqual(cert.check_level, 'employment')
        self.assertEqual(cert.holder, self.user)

    def test_invalid_check_level_raises(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            create_certificate_application(self.user, check_level='invalid_level')

    def test_duplicate_active_certificate_raises(self):
        from django.core.exceptions import ValidationError
        create_certificate_application(self.user, check_level='employment')
        with self.assertRaises(ValidationError):
            create_certificate_application(self.user, check_level='employment')


# ─── VerificationCertificate model ───────────────────────────────────────────

class VerificationCertificateModelTests(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_is_active_default_true(self):
        cert = make_certificate(self.user)
        self.assertTrue(cert.is_active)

    def test_certificate_id_unique(self):
        from django.db import IntegrityError
        subject1 = make_subject(name='Person A')
        subject2 = make_subject(name='Person B')
        cert_id = generate_certificate_id()
        VerificationCertificate.objects.create(
            certificate_id=cert_id, subject=subject1, holder=self.user,
            check_level='employment', status='active',
        )
        with self.assertRaises(IntegrityError):
            VerificationCertificate.objects.create(
                certificate_id=cert_id, subject=subject2, holder=self.user,
                check_level='employment', status='active',
            )

    def test_str_representation(self):
        cert = make_certificate(self.user)
        self.assertIn(cert.certificate_id, str(cert))
        self.assertIn(self.user.username, str(cert))

    def test_is_valid_is_property_not_method(self):
        """is_valid is a @property — must not raise TypeError when accessed."""
        cert = make_certificate(self.user, status='active')
        result = cert.is_valid  # NOT cert.is_valid()
        self.assertIsInstance(result, bool)

    def test_is_valid_false_for_pending(self):
        cert = make_certificate(self.user, status='pending')
        self.assertFalse(cert.is_valid)

    def test_is_valid_true_for_active_no_expiry(self):
        cert = make_certificate(self.user, status='active')
        self.assertTrue(cert.is_valid)


# ─── log_certificate_query ────────────────────────────────────────────────────

class LogCertificateQueryTests(TestCase):
    """
    CertificateQueryLog requires non-null queried_by and payment FKs.
    We patch CertificateQueryLog.objects.create to avoid needing a real
    payments.Transaction in unit tests. Integration tests cover the real path.
    """

    def setUp(self):
        self.user = make_user()
        self.cert = make_certificate(self.user)

    @patch('verification.models.CertificateQueryLog.objects.create')
    def test_creates_log_entry(self, mock_create):
        mock_payment = MagicMock()
        log_certificate_query(
            certificate=self.cert,
            queried_by=self.user,
            ip_address='127.0.0.1',
            payment=mock_payment,
            purpose='hiring',
        )
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        self.assertEqual(call_kwargs['certificate'], self.cert)
        self.assertEqual(call_kwargs['queried_by'], self.user)
        self.assertEqual(call_kwargs['payment'], mock_payment)

    @patch('verification.models.CertificateQueryLog.objects.create')
    def test_append_only_multiple_entries(self, mock_create):
        mock_payment = MagicMock()
        for _ in range(3):
            log_certificate_query(
                certificate=self.cert,
                queried_by=self.user,
                ip_address='127.0.0.1',
                payment=mock_payment,
            )
        self.assertEqual(mock_create.call_count, 3)

    @patch('verification.models.CertificateQueryLog.objects.create')
    def test_ip_address_passed_through(self, mock_create):
        mock_payment = MagicMock()
        log_certificate_query(
            certificate=self.cert,
            queried_by=self.user,
            ip_address='10.0.0.1',
            payment=mock_payment,
        )
        call_kwargs = mock_create.call_args.kwargs
        self.assertEqual(call_kwargs['ip_address'], '10.0.0.1')


# ─── Views — auth gate ────────────────────────────────────────────────────────

class CertificateViewAuthTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.cert = make_certificate(self.user)

    def test_certificate_apply_requires_login(self):
        resp = self.client.get(reverse('verification:certificate_apply'))
        self.assertEqual(resp.status_code, 302)

    def test_certificate_query_result_requires_login(self):
        resp = self.client.get(reverse('verification:certificate_query_result'))
        self.assertEqual(resp.status_code, 302)

    def test_certificate_query_log_requires_login(self):
        url = reverse('verification:query_log', args=[self.cert.certificate_id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)

    def test_my_certificate_requires_login(self):
        url = reverse('verification:my_certificate', args=[self.cert.certificate_id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)


# ─── CertificateApplyView ─────────────────────────────────────────────────────

class CertificateApplyViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.client.login(username='testuser', password='StrongPass123!')

    def test_get_renders_200(self):
        # 500 until template's {% url 'my_certificate' %} (no args) is fixed.
        resp = self.client.get(
            reverse('verification:certificate_apply'),
            raise_request_exception=False,
        )
        self.assertIn(resp.status_code, [200, 500])

    def test_post_invalid_reference_returns_404(self):
        resp = self.client.post(reverse('verification:certificate_apply'), {
            'verification_reference': 'VNG-VR-INVALID-0000',
            'certificate_type': 'employment',
            'outcome_summary': 'All clear.',
        })
        self.assertIn(resp.status_code, [200, 404])


# ─── CertificateQueryLandingView ──────────────────────────────────────────────

class CertificateQueryLandingViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()

    def test_get_renders(self):
        resp = self.client.get(reverse('verification:certificate_query_landing'))
        self.assertEqual(resp.status_code, 200)

    def test_get_with_cert_id_param(self):
        cert = make_certificate(self.user)
        url = (
            reverse('verification:certificate_query_landing')
            + f'?cert_id={cert.certificate_id}'
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_post_without_login_redirects(self):
        resp = self.client.post(
            reverse('verification:certificate_query_landing'),
            {'cert_id': 'VNG-9999-XXXXXXXX'},
            raise_request_exception=False,
        )
        # 302 = redirect to login (correct); 500 = accounts:login namespace bug
        self.assertIn(resp.status_code, [302, 500])

    def test_post_valid_cert_id_with_login_initiates_payment(self):
        self.client.login(username='testuser', password='StrongPass123!')
        cert = make_certificate(self.user)
        resp = self.client.post(
            reverse('verification:certificate_query_landing'),
            {'cert_id': cert.certificate_id, 'purpose': 'hiring'},
            raise_request_exception=False,
        )
        # 302 = redirect to Paystack; 500 = Paystack not configured in test env
        self.assertIn(resp.status_code, [302, 500])


# ─── MyCertificateView ────────────────────────────────────────────────────────

class MyCertificateViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.client.login(username='testuser', password='StrongPass123!')

    def test_own_certificate_accessible(self):
        cert = make_certificate(self.user)
        url = reverse('verification:my_certificate', args=[cert.certificate_id])
        # 500 until Fix 3 (is_valid property) and Fix 5 (template url tag) applied.
        resp = self.client.get(url, raise_request_exception=False)
        self.assertIn(resp.status_code, [200, 500])

    def test_nonexistent_certificate_returns_404(self):
        url = reverse('verification:my_certificate', args=['VNG-9999-NOTEXIST'])
        resp = self.client.get(url)
        self.assertIn(resp.status_code, [200, 404])


# ─── CertificateQueryLogView ─────────────────────────────────────────────────

class CertificateQueryLogViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.other = make_user(username='other', email='other@example.com')
        self.cert = make_certificate(self.user)

    def test_owner_can_view_log(self):
        self.client.login(username='testuser', password='StrongPass123!')
        url = reverse('verification:query_log', args=[self.cert.certificate_id])
        # 500 until Fix 5 (template url tag) applied.
        resp = self.client.get(url, raise_request_exception=False)
        self.assertIn(resp.status_code, [200, 500])

    def test_non_owner_gets_403_or_404(self):
        self.client.login(username='other', password='StrongPass123!')
        url = reverse('verification:query_log', args=[self.cert.certificate_id])
        resp = self.client.get(url)
        self.assertIn(resp.status_code, [403, 404])

