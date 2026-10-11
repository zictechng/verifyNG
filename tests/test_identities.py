
# tests/test_identities.py
"""
Batch 14.2 — Identity hashing and NIN/BVN validation tests.

Coverage:
  - normalize_identifier()  : valid and invalid Nigerian formats
  - hash_identifier_value() : deterministic HMAC-SHA256 digest, type-separation, pepper gate
  - SubjectEntity / Identifier model creation and uniqueness constraint
  - lookup_public_record()  : found / not-found paths
"""

import hmac
import hashlib
from unittest.mock import patch

from django.test import TestCase
from django.core.exceptions import ImproperlyConfigured

from identities.utils import (
    normalize_identifier,
    hash_identifier_value,
    get_identifier_pepper,
)
from identities.models import SubjectEntity, Identifier
from identities.services import lookup_public_record


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_subject(name='Test Person', entity_type='person'):
    return SubjectEntity.objects.create(name=name, type=entity_type)


def make_identifier(subject, id_type='phone', raw_value='08012345678'):
    value_hash = hash_identifier_value(id_type, raw_value)
    return Identifier.objects.create(
        subject=subject,
        type=id_type,
        value_hash=value_hash,
    )


# ─── Phone normalisation ──────────────────────────────────────────────────────

class PhoneNormalizationTest(TestCase):

    def test_local_11_digit_converts_to_e164(self):
        result = normalize_identifier('phone', '08012345678')
        self.assertEqual(result, '2348012345678')

    def test_e164_prefix_already_correct(self):
        result = normalize_identifier('phone', '2348012345678')
        self.assertEqual(result, '2348012345678')

    def test_plus_prefix_stripped(self):
        result = normalize_identifier('phone', '+2348012345678')
        self.assertEqual(result, '2348012345678')

    def test_spaces_stripped(self):
        result = normalize_identifier('phone', '0801 234 5678')
        self.assertEqual(result, '2348012345678')

    def test_dashes_stripped(self):
        result = normalize_identifier('phone', '080-1234-5678')
        self.assertEqual(result, '2348012345678')

    def test_wrong_length_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('phone', '0801234')   # too short

    def test_letters_in_phone_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('phone', '0801234567a')

    def test_empty_phone_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('phone', '')


# ─── NIN normalisation ────────────────────────────────────────────────────────

class NINNormalizationTest(TestCase):

    def test_valid_11_digit_nin_accepted(self):
        result = normalize_identifier('nin', '12345678901')
        self.assertEqual(result, '12345678901')

    def test_nin_with_spaces_stripped(self):
        result = normalize_identifier('nin', '1234 5678 901')
        self.assertEqual(result, '12345678901')

    def test_nin_10_digits_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('nin', '1234567890')   # 10 digits

    def test_nin_12_digits_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('nin', '123456789012')  # 12 digits

    def test_nin_with_letters_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('nin', '1234567890A')

    def test_empty_nin_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('nin', '')


# ─── BVN normalisation ────────────────────────────────────────────────────────

class BVNNormalizationTest(TestCase):

    def test_valid_11_digit_bvn_accepted(self):
        result = normalize_identifier('bvn', '22345678901')
        self.assertEqual(result, '22345678901')

    def test_bvn_with_spaces_stripped(self):
        result = normalize_identifier('bvn', '2234 5678 901')
        self.assertEqual(result, '22345678901')

    def test_bvn_wrong_length_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('bvn', '2234567890')   # 10 digits

    def test_bvn_with_letters_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('bvn', '2234567890X')

    def test_empty_bvn_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('bvn', '')


# ─── Bank account normalisation ───────────────────────────────────────────────

class BankAccountNormalizationTest(TestCase):

    def test_valid_10_digit_account_accepted(self):
        result = normalize_identifier('account', '0123456789')
        self.assertEqual(result, '0123456789')

    def test_leading_zero_preserved(self):
        """Bank account leading zeros must never be stripped."""
        result = normalize_identifier('account', '0000000001')
        self.assertEqual(result, '0000000001')

    def test_account_9_digits_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('account', '012345678')

    def test_account_11_digits_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('account', '01234567890')

    def test_empty_account_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('account', '')


# ─── CAC normalisation ────────────────────────────────────────────────────────

class CACNormalizationTest(TestCase):

    def test_rc_prefix_accepted(self):
        result = normalize_identifier('cac', 'RC123456')
        self.assertEqual(result, 'RC123456')

    def test_bn_prefix_accepted(self):
        result = normalize_identifier('cac', 'BN987654')
        self.assertEqual(result, 'BN987654')

    def test_numeric_only_prefixed_with_rc(self):
        result = normalize_identifier('cac', '123456')
        self.assertEqual(result, 'RC123456')

    def test_lowercase_normalised_to_upper(self):
        result = normalize_identifier('cac', 'rc123456')
        self.assertEqual(result, 'RC123456')

    def test_invalid_prefix_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('cac', 'XX123456')

    def test_empty_cac_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('cac', '')


# ─── Email normalisation ──────────────────────────────────────────────────────

class EmailNormalizationTest(TestCase):

    def test_valid_email_lowercased(self):
        result = normalize_identifier('email', 'Test@Example.COM')
        self.assertEqual(result, 'test@example.com')

    def test_invalid_email_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('email', 'not-an-email')

    def test_empty_email_rejected(self):
        with self.assertRaises(ValueError):
            normalize_identifier('email', '')


# ─── Unsupported type ─────────────────────────────────────────────────────────

class UnsupportedIdentifierTypeTest(TestCase):

    def test_unknown_type_raises_value_error(self):
        with self.assertRaises(ValueError):
            normalize_identifier('passport', 'A12345678')


# ─── Hashing security properties ─────────────────────────────────────────────

class IdentifierHashingTest(TestCase):

    def test_hash_is_deterministic(self):
        """Same input always produces the same digest."""
        h1 = hash_identifier_value('nin', '12345678901')
        h2 = hash_identifier_value('nin', '12345678901')
        self.assertEqual(h1, h2)

    def test_hash_is_hex_string(self):
        digest = hash_identifier_value('phone', '08012345678')
        # HMAC-SHA256 hexdigest is exactly 64 hex characters
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(c in '0123456789abcdef' for c in digest))

    def test_different_values_produce_different_hashes(self):
        h1 = hash_identifier_value('nin', '12345678901')
        h2 = hash_identifier_value('nin', '12345678902')
        self.assertNotEqual(h1, h2)

    def test_type_separation_nin_bvn_same_digits(self):
        """NIN and BVN with the same digit string must hash differently (domain prefix)."""
        digits = '12345678901'
        h_nin = hash_identifier_value('nin', digits)
        h_bvn = hash_identifier_value('bvn', digits)
        self.assertNotEqual(h_nin, h_bvn)

    def test_type_separation_phone_nin(self):
        """Phone and NIN with same digit content must produce different hashes."""
        # 08012345678 normalises to 2348012345678 (13 digits), NIN must be 11 digits
        h_phone = hash_identifier_value('phone', '08012345678')
        h_nin   = hash_identifier_value('nin',   '12345678901')
        self.assertNotEqual(h_phone, h_nin)

    def test_hash_matches_expected_hmac(self):
        """Verify the digest matches a manually computed HMAC-SHA256."""
        from django.conf import settings
        pepper  = settings.IDENTIFIER_HASH_PEPPER
        message = b'v1:nin:12345678901'
        expected = hmac.new(
            key=pepper.encode('utf-8'),
            msg=message,
            digestmod=hashlib.sha256,
        ).hexdigest()
        self.assertEqual(hash_identifier_value('nin', '12345678901'), expected)

    def test_missing_pepper_raises_improperly_configured(self):
        """Absent or empty pepper must raise ImproperlyConfigured, not silently hash."""
        with patch('identities.utils.get_identifier_pepper', side_effect=ImproperlyConfigured("no pepper")):
            with self.assertRaises(ImproperlyConfigured):
                hash_identifier_value('nin', '12345678901')

    def test_nin_never_stored_plain(self):
        """NIN plain value must NOT appear anywhere in the computed hash."""
        raw_nin = '12345678901'
        digest  = hash_identifier_value('nin', raw_nin)
        self.assertNotIn(raw_nin, digest)

    def test_bvn_never_stored_plain(self):
        """BVN plain value must NOT appear anywhere in the computed hash."""
        raw_bvn = '22345678901'
        digest  = hash_identifier_value('bvn', raw_bvn)
        self.assertNotIn(raw_bvn, digest)


# ─── Model: SubjectEntity & Identifier ───────────────────────────────────────

class SubjectEntityModelTest(TestCase):

    def test_create_person_subject(self):
        subject = make_subject(name='John Doe', entity_type='person')
        self.assertEqual(subject.type, 'person')
        self.assertTrue(subject.is_active)
        self.assertIsNotNone(subject.created_at)

    def test_create_business_subject(self):
        subject = make_subject(name='Acme Ltd', entity_type='business')
        self.assertEqual(subject.type, 'business')

    def test_str_representation(self):
        subject = make_subject(name='Jane Ojo', entity_type='person')
        self.assertIn('Jane Ojo', str(subject))


class IdentifierModelTest(TestCase):

    def setUp(self):
        self.subject = make_subject()

    def test_create_phone_identifier(self):
        identifier = make_identifier(self.subject, id_type='phone', raw_value='08012345678')
        self.assertEqual(identifier.type, 'phone')
        self.assertIsNotNone(identifier.value_hash)

    def test_create_nin_identifier(self):
        identifier = make_identifier(self.subject, id_type='nin', raw_value='12345678901')
        self.assertEqual(identifier.type, 'nin')

    def test_identifier_hash_is_64_chars(self):
        identifier = make_identifier(self.subject, id_type='bvn', raw_value='22345678901')
        self.assertEqual(len(identifier.value_hash), 64)

    def test_identifier_uniqueness_constraint(self):
        """Same identifier value must not be stored twice (unique hash constraint)."""
        from django.db import IntegrityError
        make_identifier(self.subject, id_type='nin', raw_value='12345678901')
        with self.assertRaises(IntegrityError):
            Identifier.objects.create(
                subject=self.subject,
                type='nin',
                value_hash=hash_identifier_value('nin', '12345678901'),
            )

    def test_nin_plain_value_not_in_db(self):
        """Hash stored in DB must not contain the plain NIN digits."""
        raw = '12345678901'
        identifier = make_identifier(self.subject, id_type='nin', raw_value=raw)
        self.assertNotIn(raw, identifier.value_hash)


# ─── lookup_public_record() service ──────────────────────────────────────────

class LookupPublicRecordTest(TestCase):

    def setUp(self):
        self.subject = make_subject(name='Chioma Okafor')
        self.identifier = make_identifier(self.subject, id_type='phone', raw_value='08099887766')
        self.good_hash  = self.identifier.value_hash

    def test_known_hash_returns_dict(self):
        result = lookup_public_record(self.good_hash)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)

    def test_result_contains_expected_keys(self):
        result = lookup_public_record(self.good_hash)
        required_keys = {
            'subject_name', 'entity_type', 'identity_verified',
            'has_active_flags', 'published_reports_count',
            'disputed_reports_count', 'allegation_notice',
        }
        for key in required_keys:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_result_subject_name_correct(self):
        result = lookup_public_record(self.good_hash)
        self.assertEqual(result['subject_name'], 'Chioma Okafor')

    def test_unknown_hash_returns_none(self):
        result = lookup_public_record('a' * 64)
        self.assertIsNone(result)

    def test_no_reports_means_no_active_flags(self):
        result = lookup_public_record(self.good_hash)
        self.assertFalse(result['has_active_flags'])
        self.assertEqual(result['published_reports_count'], 0)

    def test_allegation_notice_present_and_non_empty(self):
        """The legal disclaimer notice must always be returned."""
        result = lookup_public_record(self.good_hash)
        self.assertTrue(result['allegation_notice'])
        self.assertIn('unverified', result['allegation_notice'].lower())
