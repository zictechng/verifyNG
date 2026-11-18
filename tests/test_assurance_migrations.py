# tests/test_assurance_migrations.py
import importlib
from django.test import TestCase, Client
from django.apps import apps
from django.db.migrations.exceptions import IrreversibleError
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from users.models import User
from employer.models import EmployerProfile

# Import migration module dynamically to prevent Python syntax errors on numeric module names
migration_0019 = importlib.import_module('users.migrations.0019_correct_legacy_identity_assurance')
correct_legacy_identity_assurance = migration_0019.correct_legacy_identity_assurance
prevent_unsafe_reverse = migration_0019.prevent_unsafe_reverse


class IdentityAssuranceMigrationCorrectionTests(TestCase):
    """
    Tests forward execution of migration 0019 corrective logic on model instances.
    Validates lifecycle state preservation, enhanced protection, and irreversibility.
    Note: Tests migration logic directly rather than the full historical migration graph.
    """

    def test_migration_0019_logic_execution(self):
        now = timezone.now()

        # 1. Genuine reviewed NIN with identity_verified=False (Passes 4 conditions)
        u_genuine = User.objects.create(
            username='u_genuine', email='genuine@example.com', id_type='nin', id_number='12345678901',
            id_document='proofs/nin.jpg', id_verification_status='verified',
            identity_verified=False, id_verified_at=now, assurance_level='unverified'
        )

        # 2. Qualifying record ALREADY basic_verified with identity_verified=False
        # (Confirms synchronisation is not restricted to accounts promoted from unverified)
        u_basic_already = User.objects.create(
            username='u_basic_already', email='basic_already@example.com', id_type='nin', id_number='98765432101',
            id_document='proofs/nin_already.jpg', id_verification_status='verified',
            identity_verified=False, id_verified_at=now, assurance_level='basic_verified'
        )

        # 3. Enhanced Verified user with status='verified' (Must NOT be downgraded)
        u_enhanced_active = User.objects.create(
            username='u_enhanced_active', email='enhanced_active@example.com', id_type='passport', id_number='A10293847',
            id_document='proofs/pass.jpg', id_verification_status='verified',
            identity_verified=False, id_verified_at=now, assurance_level='enhanced_verified'
        )

        # 4. Enhanced Verified user with status='suspended' (Must keep enhanced, Boolean -> False)
        u_enhanced_suspended = User.objects.create(
            username='u_enhanced_suspended', email='enhanced_susp@example.com', id_type='passport', id_number='A99887766',
            id_document='proofs/pass2.jpg', id_verification_status='suspended',
            identity_verified=True, id_verified_at=now, assurance_level='enhanced_verified'
        )

        # 5. Enhanced Verified user with status='expired' (Must keep enhanced, Boolean -> False)
        u_enhanced_expired = User.objects.create(
            username='u_enhanced_expired', email='enhanced_exp@example.com', id_type='passport', id_number='A11223344',
            id_document='proofs/pass3.jpg', id_verification_status='expired',
            identity_verified=True, id_verified_at=now, assurance_level='enhanced_verified'
        )

        # 6. Enhanced Verified user with status='pending' (Must keep enhanced, Boolean -> False)
        u_enhanced_pending = User.objects.create(
            username='u_enhanced_pending', email='enhanced_pend@example.com', id_type='passport', id_number='A55667788',
            id_document='proofs/pass_pend.jpg', id_verification_status='pending',
            identity_verified=True, id_verified_at=now, assurance_level='enhanced_verified'
        )

        # 7. Admin with manually toggled Boolean only (Fails conditions)
        u_admin = User.objects.create(
            username='u_admin', email='admin_test@example.com', id_type='', id_document='',
            id_verification_status='unverified', identity_verified=True, id_verified_at=None,
            assurance_level='basic_verified'
        )

        # 8. BVN user (Never qualifies)
        u_bvn = User.objects.create(
            username='u_bvn', email='bvn_test@example.com', id_type='bvn', id_number='22233344455',
            id_document='proofs/bvn.jpg', id_verification_status='verified',
            identity_verified=True, id_verified_at=now, assurance_level='basic_verified'
        )

        # 9. Missing document file (Fails conditions)
        u_no_doc = User.objects.create(
            username='u_no_doc', email='no_doc@example.com', id_type='nin', id_document='',
            id_verification_status='verified', identity_verified=True, id_verified_at=now,
            assurance_level='basic_verified'
        )

        # 10. Missing approval timestamp (Fails conditions)
        u_no_time = User.objects.create(
            username='u_no_time', email='no_time@example.com', id_type='nin', id_document='proofs/nin2.jpg',
            id_verification_status='verified', identity_verified=True, id_verified_at=None,
            assurance_level='basic_verified'
        )

        # 11-14. Intermediate lifecycle states seeded with basic_verified (Tests preservation)
        u_rejected = User.objects.create(
            username='u_rejected', email='rejected@example.com', id_type='nin', id_document='proofs/rej.jpg',
            id_verification_status='rejected', identity_verified=False, id_rejection_reason='Blurry photo',
            assurance_level='basic_verified', id_verified_at=None
        )
        u_suspended = User.objects.create(
            username='u_suspended', email='suspended_test@example.com', id_type='nin', id_document='proofs/susp.jpg',
            id_verification_status='suspended', identity_verified=False,
            assurance_level='basic_verified', id_verified_at=now
        )
        u_expired = User.objects.create(
            username='u_expired', email='expired_test@example.com', id_type='passport', id_document='proofs/exp.jpg',
            id_verification_status='expired', identity_verified=False,
            assurance_level='basic_verified', id_verified_at=now
        )
        u_pending = User.objects.create(
            username='u_pending', email='pending_test@example.com', id_type='nin', id_document='proofs/pend.jpg',
            id_verification_status='pending', identity_verified=False,
            assurance_level='basic_verified', id_verified_at=None
        )

        # 15. Employer records
        u_emp_cac = User.objects.create(username='u_emp_cac', email='cac_emp@example.com')
        emp_cac = EmployerProfile.objects.create(
            user=u_emp_cac, company_name='Existing CAC Corp', registration_type='cac', is_verified=True
        )
        u_emp_new = User.objects.create(username='u_emp_new', email='new_emp@example.com')
        emp_new = EmployerProfile.objects.create(
            user=u_emp_new, company_name='New Unknown Corp', registration_type=''
        )

        # Execute migration logic forward
        correct_legacy_identity_assurance(apps, None)

        # --- ASSERTIONS ---

        # 1. Genuine reviewed NIN: promoted to basic_verified, Boolean corrected to True
        u_genuine.refresh_from_db()
        self.assertEqual(u_genuine.assurance_level, 'basic_verified')
        self.assertTrue(u_genuine.identity_verified)
        self.assertEqual(u_genuine.id_verification_status, 'verified')
        self.assertEqual(u_genuine.id_verified_at, now)

        # 2. Existing basic_verified account synchronized identity_verified to True
        u_basic_already.refresh_from_db()
        self.assertEqual(u_basic_already.assurance_level, 'basic_verified')
        self.assertTrue(u_basic_already.identity_verified)
        self.assertEqual(u_basic_already.id_verification_status, 'verified')

        # 3. Enhanced active user: preserved as enhanced_verified, Boolean corrected to True
        u_enhanced_active.refresh_from_db()
        self.assertEqual(u_enhanced_active.assurance_level, 'enhanced_verified')
        self.assertTrue(u_enhanced_active.identity_verified)
        self.assertEqual(u_enhanced_active.id_verification_status, 'verified')

        # 4. Enhanced suspended user: preserves enhanced_verified, but Boolean set to False
        u_enhanced_suspended.refresh_from_db()
        self.assertEqual(u_enhanced_suspended.assurance_level, 'enhanced_verified')
        self.assertFalse(u_enhanced_suspended.identity_verified)
        self.assertEqual(u_enhanced_suspended.id_verification_status, 'suspended')

        # 5. Enhanced expired user: preserves enhanced_verified, but Boolean set to False
        u_enhanced_expired.refresh_from_db()
        self.assertEqual(u_enhanced_expired.assurance_level, 'enhanced_verified')
        self.assertFalse(u_enhanced_expired.identity_verified)
        self.assertEqual(u_enhanced_expired.id_verification_status, 'expired')

        # 6. Enhanced pending user: preserves enhanced tier, but identity_verified=False
        u_enhanced_pending.refresh_from_db()
        self.assertEqual(u_enhanced_pending.assurance_level, 'enhanced_verified')
        self.assertFalse(u_enhanced_pending.identity_verified)
        self.assertEqual(u_enhanced_pending.id_verification_status, 'pending')

        # 7. Admin account: reset to unverified, Boolean corrected to False
        u_admin.refresh_from_db()
        self.assertEqual(u_admin.assurance_level, 'unverified')
        self.assertFalse(u_admin.identity_verified)
        self.assertEqual(u_admin.id_verification_status, 'unverified')

        # 8. BVN never qualifies: reset to unverified, document preserved
        u_bvn.refresh_from_db()
        self.assertEqual(u_bvn.assurance_level, 'unverified')
        self.assertFalse(u_bvn.identity_verified)
        self.assertEqual(u_bvn.id_verification_status, 'unverified')
        self.assertEqual(u_bvn.id_document, 'proofs/bvn.jpg')

        # 9. Missing document & timestamp: reset to unverified
        u_no_doc.refresh_from_db()
        self.assertEqual(u_no_doc.assurance_level, 'unverified')
        self.assertFalse(u_no_doc.identity_verified)

        u_no_time.refresh_from_db()
        self.assertEqual(u_no_time.assurance_level, 'unverified')
        self.assertFalse(u_no_time.identity_verified)

        # 10. Intermediate lifecycle states preserved
        u_rejected.refresh_from_db()
        self.assertEqual(u_rejected.assurance_level, 'unverified')
        self.assertEqual(u_rejected.id_verification_status, 'rejected')
        self.assertEqual(u_rejected.id_rejection_reason, 'Blurry photo')

        u_suspended.refresh_from_db()
        self.assertEqual(u_suspended.assurance_level, 'unverified')
        self.assertEqual(u_suspended.id_verification_status, 'suspended')

        u_expired.refresh_from_db()
        self.assertEqual(u_expired.assurance_level, 'unverified')
        self.assertEqual(u_expired.id_verification_status, 'expired')

        u_pending.refresh_from_db()
        self.assertEqual(u_pending.assurance_level, 'unverified')
        self.assertEqual(u_pending.id_verification_status, 'pending')

        # 11. Employer records
        emp_cac.refresh_from_db()
        self.assertEqual(emp_cac.registration_type, 'cac')
        emp_new.refresh_from_db()
        self.assertEqual(emp_new.registration_type, '')

    def test_migration_0019_is_irreversible(self):
        """Reversing migration 0019 explicitly raises IrreversibleError."""
        with self.assertRaises(IrreversibleError):
            prevent_unsafe_reverse(apps, None)

    def test_bvn_post_causes_no_file_or_db_mutation(self):
        """Server-side BVN POST restriction causes zero file or DB mutation."""
        client = Client()
        user = User.objects.create_user(
            username='bvn_post_test', email='bvn_poster@verifyng.com', password='TestPassword123!'
        )
        client.force_login(user)
        dummy_file = SimpleUploadedFile("bvn_card.jpg", b"fake binary data", content_type="image/jpeg")

        response = client.post(reverse('users:verify_identity_submit'), {
            'id_type': 'bvn',
            'id_number': '22233344455',
            'id_document': dummy_file
        })

        user.refresh_from_db()
        self.assertEqual(user.id_type, '')
        self.assertEqual(user.id_number, '')
        self.assertFalse(user.has_id_document)
        self.assertEqual(user.id_verification_status, 'unverified')
        self.assertEqual(user.assurance_level, 'unverified')
        self.assertFalse(user.identity_verified)
