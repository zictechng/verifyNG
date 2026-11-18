# Generated manually for VerifyNG Phase 1
from django.db import migrations


def backfill_legacy_identity_assurance(apps, schema_editor):
    """
    Backfills existing verified users to 'basic_verified' assurance level.
    Only classifies accounts where identity_verified is True or id_verification_status is 'verified'.
    Strictly preserves existing verification timestamps and does NOT invent country data.
    """
    User = apps.get_model('users', 'User')

    # Find legacy verified users whose assurance level is currently 'unverified'
    legacy_verified = User.objects.filter(
        assurance_level='unverified'
    ).filter(
        identity_verified=True
    ) | User.objects.filter(
        assurance_level='unverified',
        id_verification_status='verified'
    )

    # Distinct update to basic_verified
    count = legacy_verified.distinct().update(assurance_level='basic_verified')
    if count:
        print(f" [DataMigration] Successfully mapped {count} legacy verified user(s) to 'basic_verified'.")


def reverse_legacy_identity_assurance(apps, schema_editor):
    """
    Rollback: reset assurance_level to 'unverified'.
    """
    User = apps.get_model('users', 'User')
    User.objects.filter(assurance_level='basic_verified').update(assurance_level='unverified')


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0017_add_identity_assurance_and_country'),
    ]

    operations = [
        migrations.RunPython(
            backfill_legacy_identity_assurance,
            reverse_code=reverse_legacy_identity_assurance
        ),
    ]
