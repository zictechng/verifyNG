from django.test import TestCase
from users.country_config import (
    get_country_business_config,
    validate_business_registration,
    is_country_supported,
)


class CountryBusinessConfigTests(TestCase):
    """
    Unit tests for Pan-African Corporate & Business Registration Configuration (Batch 1).
    Covers NG, GH, KE, BJ, CI, SN, ZA, legacy fallbacks, and strict unknown country rejection.
    """

    def test_legacy_account_defaults_to_nigeria_cac(self):
        """Legacy accounts with country=None or '' default to Nigeria CAC."""
        cfg_none = get_country_business_config(None)
        self.assertIsNotNone(cfg_none)
        self.assertEqual(cfg_none['code'], 'NG')
        self.assertEqual(cfg_none['name'], 'Nigeria')
        self.assertIn('cac', cfg_none['registration_types'])

        cfg_empty = get_country_business_config('')
        self.assertIsNotNone(cfg_empty)
        self.assertEqual(cfg_empty['code'], 'NG')

    def test_unsupported_country_returns_none(self):
        """Unknown or unsupported country codes must reject cleanly and NEVER silently become Nigeria."""
        self.assertIsNone(get_country_business_config('ZZ'))
        self.assertIsNone(get_country_business_config('US'))
        self.assertIsNone(get_country_business_config('FR'))

        is_valid, err, _ = validate_business_registration('ZZ', 'cac', '123456')
        self.assertFalse(is_valid)
        self.assertIn("not currently supported", err)

    def test_nigeria_cac_validation(self):
        """Nigeria CAC formats: RC, BN, IT, digits only, and TIN."""
        valid_cases = [
            ('RC-1234567', 'RC-1234567'),
            ('RC1234567', 'RC1234567'),
            ('BN-987654', 'BN-987654'),
            ('IT-54321', 'IT-54321'),
            ('123456', '123456'),
        ]
        for raw, expected in valid_cases:
            is_valid, err, cleaned = validate_business_registration('NG', 'cac', raw, tin_number='12345678-0001')
            self.assertTrue(is_valid, f"Failed for valid CAC number {raw}: {err}")
            self.assertEqual(cleaned['reg_number'], expected)
            self.assertEqual(cleaned['tin_number'], '12345678-0001')

        # Invalid CAC numbers
        invalid_cases = ['123', 'TOO_SHORT', 'INVALID_PREFIX-1234567890123']
        for bad in invalid_cases:
            is_valid, err, _ = validate_business_registration('NG', 'cac', bad)
            self.assertFalse(is_valid, f"Expected failure for {bad}")

    def test_ghana_orc_validation(self):
        """Ghana ORC formats: CS, CA, BN, PL, and GRA TIN / Ghana Card PIN."""
        valid_cases = ['CS123452021', 'BN-987654321', 'CA1234567']
        for raw in valid_cases:
            is_valid, err, cleaned = validate_business_registration('GH', 'orc', raw, tin_number='P0012345678')
            self.assertTrue(is_valid, f"Failed for valid ORC number {raw}: {err}")

        # Invalid format
        is_valid, err, _ = validate_business_registration('GH', 'orc', '12345')
        self.assertFalse(is_valid)

        # Invalid TIN
        is_valid, err, _ = validate_business_registration('GH', 'orc', 'CS1234567', tin_number='INVALID_TIN')
        self.assertFalse(is_valid)
        self.assertIn("Tax Identification Number", err)

    def test_kenya_brs_validation(self):
        """Kenya BRS formats: CPR/YYYY/NNNN, BN/YYYY/NNNN, PVT-XXXX, and KRA PIN."""
        valid_cases = ['CPR/2021/12345', 'PVT-ABC1234', 'BN/2019/54321']
        for raw in valid_cases:
            is_valid, err, cleaned = validate_business_registration('KE', 'brs', raw, tin_number='P051234567Z')
            self.assertTrue(is_valid, f"Failed for valid BRS number {raw}: {err}")

        # Invalid KRA PIN
        is_valid, err, _ = validate_business_registration('KE', 'brs', 'CPR/2021/12345', tin_number='123456')
        self.assertFalse(is_valid)
        self.assertIn("KRA PIN", err)

    def test_benin_rccm_validation(self):
        """Benin RCCM: RB/COT/20 B 12345 and 13-digit IFU."""
        is_valid, err, cleaned = validate_business_registration(
            'BJ', 'rccm', 'RB/COT/20 B 12345', tin_number='1234567890123'
        )
        self.assertTrue(is_valid, f"Failed for valid Benin RCCM: {err}")
        self.assertEqual(cleaned['tin_number'], '1234567890123')

        # Invalid IFU (must be 13 digits)
        is_valid, err, _ = validate_business_registration('BJ', 'rccm', 'RB/COT/20 B 12345', tin_number='12345')
        self.assertFalse(is_valid)
        self.assertIn("Identifiant Fiscal Unique", err)

    def test_cote_divoire_rccm_validation(self):
        """Côte d'Ivoire RCCM: CI-ABJ-2020-B-12345 and NCC (7 digits + 1 letter)."""
        is_valid, err, cleaned = validate_business_registration(
            'CI', 'rccm', 'CI-ABJ-2020-B-12345', tin_number='1234567A'
        )
        self.assertTrue(is_valid, f"Failed for valid CI RCCM: {err}")
        self.assertEqual(cleaned['tin_number'], '1234567A')

        # Invalid NCC
        is_valid, err, _ = validate_business_registration('CI', 'rccm', 'CI-ABJ-2020-B-12345', tin_number='12345')
        self.assertFalse(is_valid)
        self.assertIn("Numéro de Compte Contribuable", err)

    def test_senegal_rccm_validation(self):
        """Senegal RCCM: SN.DKR.2021.B.12345 and NINEA (9 digits)."""
        is_valid, err, cleaned = validate_business_registration(
            'SN', 'rccm', 'SN.DKR.2021.B.12345', tin_number='0012345672V3'
        )
        self.assertTrue(is_valid, f"Failed for valid Senegal RCCM: {err}")

        # Invalid NINEA
        is_valid, err, _ = validate_business_registration('SN', 'rccm', 'SN.DKR.2021.B.12345', tin_number='123')
        self.assertFalse(is_valid)
        self.assertIn("NINEA", err)

    def test_south_africa_cipc_validation(self):
        """South Africa CIPC: YYYY/NNNNNN/NN and SARS 10-digit tax reference."""
        is_valid, err, cleaned = validate_business_registration(
            'ZA', 'cipc', '2019/123456/07', tin_number='9123456789'
        )
        self.assertTrue(is_valid, f"Failed for valid CIPC Enterprise Number: {err}")
        self.assertEqual(cleaned['tin_number'], '9123456789')

        # Invalid SARS tax number (must start with 9 and have 10 digits)
        is_valid, err, _ = validate_business_registration('ZA', 'cipc', '2019/123456/07', tin_number='1234567890')
        self.assertFalse(is_valid)
        self.assertIn("SARS", err)
