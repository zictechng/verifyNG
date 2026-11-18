# tests/test_country_config.py
"""
Unit and integration test suite for Pan-African Country Configuration (Step 4).
Tests:
- Central registry and supported country lookups
- Country of residence vs document-issuing country separation
- Country-specific document validation (Nigeria, Ghana, Kenya, Benin, South Africa, Côte d'Ivoire, Senegal)
- Non-silence on unknown/unsupported countries (must never silently default to Nigeria)
- Strict BVN exclusion
- Profile submission view handling
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from users.models import User
from users.country_config import (
    is_country_supported,
    get_country_config,
    get_supported_countries,
    get_country_documents,
    validate_document_number,
    DEFAULT_COUNTRY,
)
from reports.models import AuditLog


class CountryConfigRegistryTests(TestCase):
    def test_supported_countries_resolution(self):
        """Supported African countries are recognized; unknown codes are not."""
        for code in ('NG', 'ng', 'GH', 'gh', 'KE', 'ke', 'BJ', 'bj', 'ZA', 'za', 'CI', 'ci', 'SN', 'sn'):
            self.assertTrue(is_country_supported(code))

        for invalid in (None, '', 'XX', 'US', 'GB', 'FR', 'ZZ'):
            self.assertFalse(is_country_supported(invalid))

    def test_default_country_is_nigeria_for_none(self):
        """None or empty string safely defaults to Nigeria for legacy backward compatibility."""
        cfg_none = get_country_config(None)
        self.assertIsNotNone(cfg_none)
        self.assertEqual(cfg_none['code'], 'NG')
        self.assertEqual(cfg_none['name'], 'Nigeria')
        self.assertIn('nin', cfg_none['accepted_documents'])

        cfg_empty = get_country_config('')
        self.assertIsNotNone(cfg_empty)
        self.assertEqual(cfg_empty['code'], 'NG')

    def test_unsupported_country_does_not_silently_become_nigeria(self):
        """Unknown or unsupported countries MUST return None and not silently become Nigeria."""
        for unsupported in ('XX', 'YY', 'FR', 'DE', 'UNKNOWN'):
            cfg = get_country_config(unsupported)
            self.assertIsNone(cfg, f"Country {unsupported} should return None, but returned a config.")

    def test_supported_countries_list_ordering(self):
        """Nigeria is placed first in dropdown tuples, followed alphabetically by other nations."""
        countries = get_supported_countries()
        self.assertEqual(countries[0], ('NG', 'Nigeria'))
        codes = [c[0] for c in countries]
        self.assertIn('GH', codes)
        self.assertIn('KE', codes)
        self.assertIn('BJ', codes)
        self.assertIn('ZA', codes)

    def test_benin_has_distinct_cip_and_cni(self):
        """Benin documentation recognizes CIP (10-digit NPI) and CNI as distinct documents."""
        cfg = get_country_config('BJ')
        self.assertIsNotNone(cfg)
        docs = cfg['accepted_documents']
        self.assertIn('cip', docs)
        self.assertIn('cni', docs)
        self.assertNotEqual(docs['cip']['regex'], docs['cni']['regex'])


class DocumentNumberValidationTests(TestCase):
    def test_strict_bvn_exclusion(self):
        """BVN must be strictly rejected across all countries as a financial identifier."""
        for country in ('NG', 'GH', 'KE', None, ''):
            valid, msg = validate_document_number(country, 'bvn', '12345678901')
            self.assertFalse(valid)
            self.assertIn('financial identifier', msg)

    def test_nigeria_document_validation(self):
        """Tests Nigerian NIN, PVC, and Passport format checks."""
        # NIN: 11 digits
        valid, res = validate_document_number('NG', 'nin', '12345678901')
        self.assertTrue(valid)
        self.assertEqual(res, '12345678901')

        # NIN with formatting dashes cleaned
        valid, res = validate_document_number('NG', 'nin', '123-456-78901')
        self.assertTrue(valid)
        self.assertEqual(res, '12345678901')

        # Invalid NIN: 10 digits
        valid, msg = validate_document_number('NG', 'nin', '1234567890')
        self.assertFalse(valid)
        self.assertIn('11 digits', msg)

        # Nigerian Passport: 1 letter + 8 digits
        valid, res = validate_document_number('NG', 'passport', 'A12345678')
        self.assertTrue(valid)
        self.assertEqual(res, 'A12345678')

        valid, msg = validate_document_number('NG', 'passport', '12345678')
        self.assertFalse(valid)

    def test_ghana_card_validation(self):
        """Tests Ghana Card PIN format: GHA-XXXXXXXXX-X."""
        valid, res = validate_document_number('GH', 'ghana_card', 'GHA-123456789-0')
        self.assertTrue(valid)
        self.assertEqual(res, 'GHA-123456789-0')

        # 10 digits middle variant
        valid, res = validate_document_number('GH', 'ghana_card', 'GHA-1234567890-1')
        self.assertTrue(valid)

        # Invalid format
        valid, msg = validate_document_number('GH', 'ghana_card', '1234567890')
        self.assertFalse(valid)
        self.assertIn('GHA-', msg)

        # NIN submitted under Ghana
        valid, msg = validate_document_number('GH', 'nin', '12345678901')
        self.assertFalse(valid)
        self.assertIn('not accepted for Ghana', msg)

    def test_kenya_national_id_validation(self):
        """Tests Kenyan National ID (7 to 9 digits)."""
        valid, res = validate_document_number('KE', 'national_id', '12345678')
        self.assertTrue(valid)
        self.assertEqual(res, '12345678')

        valid, msg = validate_document_number('KE', 'national_id', '12345')
        self.assertFalse(valid)
        self.assertIn('between 7 and 9 digits', msg)

    def test_benin_cip_validation(self):
        """Tests Benin CIP 10-digit NPI."""
        valid, res = validate_document_number('BJ', 'cip', '1234567890')
        self.assertTrue(valid)
        self.assertEqual(res, '1234567890')

        valid, msg = validate_document_number('BJ', 'cip', '12345678')
        self.assertFalse(valid)
        self.assertIn('10-digit', msg)

    def test_south_africa_id_luhn_checksum(self):
        """Tests South African 13-digit ID with Luhn algorithm validation."""
        # Calculate a valid 13-digit ID: 9001015009087 (example with valid Luhn)
        # Using a known valid test ID or checking invalid rejection:
        valid, msg = validate_document_number('ZA', 'national_id', '1234567890123')
        # Arbitrary digits will fail the Luhn checksum
        self.assertFalse(valid)
        self.assertIn('valid checksum', msg)

    def test_unsupported_country_validation_rejection(self):
        """Validation for an unsupported country code is rejected explicitly."""
        valid, msg = validate_document_number('XX', 'passport', 'A12345678')
        self.assertFalse(valid)
        self.assertIn("not currently supported", msg)

    def test_cross_border_residence_vs_issuing_country(self):
        """
        Cross-border scenario: A user resident in Nigeria submitting a Ghana Card,
        or a user resident in Ghana submitting a Nigerian NIN.
        """
        # User in Nigeria submitting a Ghana Card (issuing_country='GH')
        valid, res = validate_document_number('GH', 'ghana_card', 'GHA-987654321-4')
        self.assertTrue(valid)
        self.assertEqual(res, 'GHA-987654321-4')

        # User in Ghana submitting a Nigerian NIN (issuing_country='NG')
        valid, res = validate_document_number('NG', 'nin', '98765432109')
        self.assertTrue(valid)
        self.assertEqual(res, '98765432109')


class UserIdentityVerificationSubmitViewIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='applicant_pan_african',
            email='panafrican@verifyng.local',
            password='TestPassword123!',
            country='GH'  # Residence is Ghana
        )
        self.client.force_login(self.user)
        self.url = reverse('users:verify_identity_submit')
        self.sample_pdf = SimpleUploadedFile("id_scan.pdf", b"%PDF-1.4 test document content", content_type="application/pdf")

    def test_successful_ghana_card_submission(self):
        """Ghanaian resident submits Ghana Card with issuing_country=GH."""
        response = self.client.post(self.url, {
            'issuing_country': 'GH',
            'id_type': 'ghana_card',
            'id_number': 'GHA-123456789-0',
            'id_document': self.sample_pdf
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.id_type, 'ghana_card')
        self.assertEqual(self.user.id_number, 'GHA-123456789-0')
        self.assertEqual(self.user.id_verification_status, 'pending')

        # Audit log verification
        log = AuditLog.objects.filter(action="USER_IDENTITY_VERIFICATION_SUBMITTED", performed_by=self.user).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.details.get('issuing_country'), 'GH')

    def test_legacy_nigerian_submission_without_issuing_country(self):
        """Legacy account submitting NIN without specifying issuing_country defaults to Nigeria."""
        self.user.country = None
        self.user.save(update_fields=['country'])

        pdf = SimpleUploadedFile("nin_slip.pdf", b"%PDF-1.4 nin", content_type="application/pdf")
        response = self.client.post(self.url, {
            'id_type': 'nin',
            'id_number': '11223344556',
            'id_document': pdf
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.id_type, 'nin')
        self.assertEqual(self.user.id_number, '11223344556')
        self.assertEqual(self.user.id_verification_status, 'pending')

    def test_submission_rejects_bvn(self):
        """Submitting BVN via POST is strictly declined without saving."""
        pdf = SimpleUploadedFile("fake.pdf", b"%PDF-1.4", content_type="application/pdf")
        response = self.client.post(self.url, {
            'issuing_country': 'NG',
            'id_type': 'bvn',
            'id_number': '12345678901',
            'id_document': pdf
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.id_type, 'bvn')

    def test_submission_rejects_unsupported_issuing_country(self):
        """Submitting an ID for an unsupported country reports error without mutation."""
        pdf = SimpleUploadedFile("id.pdf", b"%PDF-1.4", content_type="application/pdf")
        response = self.client.post(self.url, {
            'issuing_country': 'XX',
            'id_type': 'passport',
            'id_number': 'A12345678',
            'id_document': pdf
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.id_verification_status, 'unverified')
