# tests/test_migration_0020_data.py

from django.test import TransactionTestCase
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

class Migration0020DataTests(TransactionTestCase):
    # TransactionTestCase is required for MigrationExecutor to manage transactions and schema state
    reset_sequences = True

    def test_migration_0020_qualifying_and_non_qualifying_users(self):
        """
        Tests Migration 0020 forward data migration using MigrationExecutor.
        Verifies that ONLY users satisfying all SIX qualifying conditions from Migration 0019
        receive can_publish_reports=True:
          1. id_verification_status == 'verified'
          2. identity_verified == True
          3. id_type in ACCEPTABLE_DOCS (BVN excluded)
          4. id_document is present and non-empty
          5. id_verified_at is not null
          6. is_suspended == False
        """
        executor = MigrationExecutor(connection)
        migrate_from = [('users', '0019_correct_legacy_identity_assurance')]
        migrate_to = [('users', '0020_add_report_publishing_and_alternative_verification')]

        try:
            # 1. Roll back schema to Migration 0019 state
            executor.migrate(migrate_from)
            old_apps = executor.loader.project_state(migrate_from).apps
            OldUser = old_apps.get_model('users', 'User')

            now = timezone.now()

            # 2. Seed historical user records under Migration 0019 schema:

            # Case A: Fully Qualifying User (Satisfies all 6 conditions)
            user_qualifying = OldUser.objects.create(
                username='user_qualifying_nin',
                email='qualifying_nin@verifyng.com',
                id_verification_status='verified',      # Condition 1
                identity_verified=True,                  # Condition 2
                id_type='nin',                           # Condition 3 (approved document)
                id_document='identity_proofs/nin.jpg',   # Condition 4 (non-empty document)
                id_verified_at=now,                      # Condition 5 (timestamp present)
                is_suspended=False                       # Condition 6 (not suspended)
            )

            # Case B: BVN User (Fails Condition 3: BVN excluded)
            user_bvn = OldUser.objects.create(
                username='user_bvn_only',
                email='bvn@verifyng.com',
                id_verification_status='verified',
                identity_verified=True,
                id_type='bvn',
                id_document='identity_proofs/bvn.jpg',
                id_verified_at=now,
                is_suspended=False
            )

            # Case C: User with No Document (Fails Condition 4: empty document string)
            user_no_doc = OldUser.objects.create(
                username='user_no_document',
                email='nodoc@verifyng.com',
                id_verification_status='verified',
                identity_verified=True,
                id_type='nin',
                id_document='',
                id_verified_at=now,
                is_suspended=False
            )

            # Case D: User without Timestamp (Fails Condition 5: id_verified_at is None)
            user_no_timestamp = OldUser.objects.create(
                username='user_no_timestamp',
                email='notimestamp@verifyng.com',
                id_verification_status='verified',
                identity_verified=True,
                id_type='passport',
                id_document='identity_proofs/passport.jpg',
                id_verified_at=None,
                is_suspended=False
            )

            # Case E: Suspended User (Fails Condition 6: is_suspended is True)
            user_suspended = OldUser.objects.create(
                username='user_suspended',
                email='suspended@verifyng.com',
                id_verification_status='verified',
                identity_verified=True,
                id_type='voters_card',
                id_document='identity_proofs/pvc.jpg',
                id_verified_at=now,
                is_suspended=True
            )

            # Case F: Unverified Status (Fails Condition 1: status is 'pending')
            user_unverified = OldUser.objects.create(
                username='user_pending_status',
                email='pending@verifyng.com',
                id_verification_status='pending',
                identity_verified=False,
                id_type='nin',
                id_document='identity_proofs/nin2.jpg',
                id_verified_at=now,
                is_suspended=False
            )

            # 3. Apply Migration 0020 forward
            executor.loader.build_graph()
            executor.migrate(migrate_to)

            # 4. Inspect results using new schema models
            new_apps = executor.loader.project_state(migrate_to).apps
            NewUser = new_apps.get_model('users', 'User')

            u_qualifying = NewUser.objects.get(id=user_qualifying.id)
            u_bvn = NewUser.objects.get(id=user_bvn.id)
            u_no_doc = NewUser.objects.get(id=user_no_doc.id)
            u_no_timestamp = NewUser.objects.get(id=user_no_timestamp.id)
            u_suspended = NewUser.objects.get(id=user_suspended.id)
            u_unverified = NewUser.objects.get(id=user_unverified.id)

            # 5. Assert strict synchronization: ONLY Case A is promoted
            self.assertTrue(u_qualifying.can_publish_reports, "User meeting all 6 conditions MUST have can_publish_reports=True")
            self.assertFalse(u_bvn.can_publish_reports, "BVN user MUST NOT receive can_publish_reports=True")
            self.assertFalse(u_no_doc.can_publish_reports, "User without document file MUST NOT receive can_publish_reports=True")
            self.assertFalse(u_no_timestamp.can_publish_reports, "User without id_verified_at MUST NOT receive can_publish_reports=True")
            self.assertFalse(u_suspended.can_publish_reports, "Suspended user MUST NOT receive can_publish_reports=True")
            self.assertFalse(u_unverified.can_publish_reports, "Unverified user MUST NOT receive can_publish_reports=True")

        finally:
            # 6. Guaranteed Cleanup: Always restore schema to latest state even if assertions fail
            executor.loader.build_graph()
            latest_migrations = executor.loader.graph.leaf_nodes('users')
            executor.migrate(latest_migrations)
