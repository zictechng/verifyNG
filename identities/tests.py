from django.test import TestCase, override_settings
from django.core.exceptions import ImproperlyConfigured
from identities.models import SubjectEntity, Identifier, BusinessProfile
from identities.utils import normalize_identifier, hash_identifier_value
from reports.models import FraudReport
from verification.models import VerificationRequest, VerificationResult
from identities.services import lookup_public_record


class IdentitiesTestCase(TestCase):
    def setUp(self):
        self.subject = SubjectEntity.objects.create(type='person', name='Mock Person')
        self.identifier = Identifier.objects.create(subject=self.subject, type='phone', value_hash='mock_hash_123')

    def test_subject_creation(self):
        self.assertEqual(SubjectEntity.objects.count(), 1)
        self.assertEqual(self.subject.name, 'Mock Person')

    def test_identifier_creation(self):
        self.assertEqual(Identifier.objects.count(), 1)
        self.assertEqual(self.identifier.value_hash, 'mock_hash_123')


class IdentifierHashingTestCase(TestCase):

    @override_settings(IDENTIFIER_HASH_PEPPER="test-secret-pepper-12345")
    def test_hash_determinism(self):
        hash1 = hash_identifier_value('phone', '(080) 123-45678')
        hash2 = hash_identifier_value('phone', '+234 801.234.5678')
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)

    @override_settings(IDENTIFIER_HASH_PEPPER="test-secret-pepper-12345")
    def test_domain_type_separation(self):
        # Same 11 digits as phone vs NIN must produce completely different hashes
        val = '08012345678'
        phone_hash = hash_identifier_value('phone', val)
        nin_hash = hash_identifier_value('nin', val)
        self.assertNotEqual(phone_hash, nin_hash)

    def test_phone_normalization_valid_delimiters(self):
        self.assertEqual(normalize_identifier('phone', '08023456789'), '2348023456789')
        self.assertEqual(normalize_identifier('phone', '(080) 234-56789'), '2348023456789')
        self.assertEqual(normalize_identifier('phone', '+234-802.345.6789'), '2348023456789')

    def test_phone_normalization_invalid_characters_and_no_leak(self):
        with self.assertRaises(ValueError) as ctx:
            normalize_identifier('phone', '08012345678abc')
        # Ensure raw input is not in the error message
        self.assertNotIn('08012345678abc', str(ctx.exception))

    def test_leading_zero_preservation(self):
        self.assertEqual(normalize_identifier('account', '0123456789'), '0123456789')
        self.assertEqual(normalize_identifier('nin', '01234567890'), '01234567890')
        self.assertEqual(normalize_identifier('bvn', '01234567890'), '01234567890')

    @override_settings(IDENTIFIER_HASH_PEPPER="")
    def test_missing_pepper_raises_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured):
            hash_identifier_value('phone', '08012345678')


class Phase7IdentifierNormalizationTestCase(TestCase):
    @override_settings(IDENTIFIER_HASH_PEPPER="test-pepper-phase7")
    def test_cac_normalization_formats(self):
        # 1. Prefixed formats normalize to uppercase alphanumeric
        self.assertEqual(normalize_identifier('cac', 'RC 123456'), 'RC123456')
        self.assertEqual(normalize_identifier('cac', 'rc-123456'), 'RC123456')
        self.assertEqual(normalize_identifier('cac', 'bn 987654'), 'BN987654')
        self.assertEqual(normalize_identifier('cac', 'IT 45678'), 'IT45678')

        # 2. Purely numeric CAC inputs automatically prepend 'RC'
        self.assertEqual(normalize_identifier('cac', '1234567'), 'RC1234567')

        # 3. Invalid formats rejected without leaking input
        with self.assertRaises(ValueError) as ctx:
            normalize_identifier('cac', 'INVALID@#$')
        self.assertNotIn('INVALID@#$', str(ctx.exception))

    @override_settings(IDENTIFIER_HASH_PEPPER="test-pepper-phase7")
    def test_email_normalization(self):
        # 1. Lowercased and trimmed
        self.assertEqual(normalize_identifier('email', '  User.Test@Domain.COM  '), 'user.test@domain.com')

        # 2. Invalid syntax rejected
        with self.assertRaises(ValueError) as ctx:
            normalize_identifier('email', 'not-an-email')
        self.assertNotIn('not-an-email', str(ctx.exception))


class Phase7StatusSeparationServiceTestCase(TestCase):
    def setUp(self):
        self.subject = SubjectEntity.objects.create(type='business', name='Tech Corp')
        self.identifier = Identifier.objects.create(
            subject=self.subject,
            type='cac',
            value_hash='hash_tech_corp_123'
        )

    def test_status_separation_verified_business_and_published_allegations(self):
        # 1. Mark business as officially verified
        BusinessProfile.objects.create(
            subject=self.subject,
            official_name='Tech Corp Nigeria Ltd',
            registration_number='RC123456',
            is_verified_business=True
        )

        # 2. Add published fraud report and unreviewed fraud report with distinct reference numbers
        FraudReport.objects.create(
            reference_number='VNG-TEST-0001',
            target_subject=self.subject,
            title='Delayed Delivery',
            allegation='Item delivered late.',
            state='published'
        )
        FraudReport.objects.create(
            reference_number='VNG-TEST-0002',
            target_subject=self.subject,
            title='Unreviewed Claim',
            allegation='Pending review.',
            state='submitted'
        )

        record = lookup_public_record('hash_tech_corp_123')
        self.assertIsNotNone(record)
        self.assertTrue(record['identity_verified'])
        self.assertEqual(record['verification_label'], 'Officially Verified')
        self.assertTrue(record['has_active_flags'])
        # Only published report is counted; 'submitted' is excluded
        self.assertEqual(record['published_reports_count'], 1)
        self.assertEqual(record['disputed_reports_count'], 0)
        self.assertEqual(record['official_business_name'], 'Tech Corp Nigeria Ltd')
        self.assertIn('unverified community allegations', record['allegation_notice'])

    def test_status_separation_unverified_entity(self):
        record = lookup_public_record('hash_tech_corp_123')
        self.assertIsNotNone(record)
        self.assertFalse(record['identity_verified'])
        self.assertFalse(record['has_active_flags'])
        self.assertEqual(record['published_reports_count'], 0)
        self.assertEqual(record['verification_label'], 'Unverified (No Official Verification on File)')

