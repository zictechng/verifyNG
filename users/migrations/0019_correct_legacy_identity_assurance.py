# users/migrations/0019_correct_legacy_identity_assurance.py
from django.db import migrations
from django.db.models import Q
from django.db.migrations.exceptions import IrreversibleError

ACCEPTABLE_IDENTITY_DOCUMENTS = {
    'nin', 'voters_card', 'passport', 'drivers_license', 
    'ghana_card', 'cip', 'cni', 'national_id'
}

def correct_legacy_identity_assurance(apps, schema_editor):
    """
    Forward-only bi-directional synchronization migration:
    
    1. QUALIFYING BASIC RECORDS (Pass all 4 criteria):
       - id_verification_status == 'verified'
       - id_type in ACCEPTABLE_IDENTITY_DOCUMENTS (BVN strictly excluded)
       - id_document is present and non-empty
       - id_verified_at is not null
       -> Ensures EVERY account passing all 4 criteria has:
            assurance_level='basic_verified', identity_verified=True, id_verification_status='verified'.
       -> Does NOT restrict synchronization to accounts newly promoted from 'unverified'.
       
    2. ENHANCED VERIFIED RECORDS (Lifecycle Integrity):
       -> Preserves assurance_level='enhanced_verified' (never downgraded).
       -> Preserves the exact lifecycle id_verification_status.
       -> If id_verification_status == 'verified':
            synchronizes identity_verified=True.
       -> For EVERY OTHER lifecycle status (pending, unverified, suspended, rejected, expired):
            synchronizes identity_verified=False (prevents permission gate bypass).

    3. NON-QUALIFYING BASIC RECORDS (Fail criteria):
       -> Resets assurance_level from 'basic_verified' to 'unverified'.
       -> Sets identity_verified=False.
       -> Resets id_verification_status to 'unverified' ONLY if current value was 'verified'.
       -> PRESERVES intermediate lifecycle states: 'rejected', 'suspended', 'expired', 'pending'.
       -> PRESERVES all historical documents, notes, rejection reasons, and timestamps.
    """
    User = apps.get_model('users', 'User')

    qualifying_q = (
        Q(id_verification_status='verified') &
        Q(id_type__in=ACCEPTABLE_IDENTITY_DOCUMENTS) &
        Q(id_document__gt='') &
        Q(id_verified_at__isnull=False)
    )

    # --- PART A: Synchronize All Valid Qualifying Basic Records ---
    # Targets any qualifying account not in enhanced tier, regardless of prior assurance_level
    qualifying_basic = User.objects.filter(qualifying_q).exclude(assurance_level='enhanced_verified')
    promoted_count = 0
    for user in qualifying_basic:
        needs_update = False
        if user.assurance_level != 'basic_verified':
            user.assurance_level = 'basic_verified'
            needs_update = True
        if not user.identity_verified:
            user.identity_verified = True
            needs_update = True
        if user.id_verification_status != 'verified':
            user.id_verification_status = 'verified'
            needs_update = True

        if needs_update:
            user.save(update_fields=['assurance_level', 'identity_verified', 'id_verification_status'])
            promoted_count += 1

    if promoted_count:
        print(f" [Migration 0019] Synchronized {promoted_count} qualifying user(s) to 'basic_verified' (identity_verified=True).")

    # --- PART B: Synchronize Enhanced Verified Lifecycle Integrity ---
    enhanced_users = User.objects.filter(assurance_level='enhanced_verified')
    enhanced_sync_count = 0
    for user in enhanced_users:
        needs_update = False
        if user.id_verification_status == 'verified':
            if not user.identity_verified:
                user.identity_verified = True
                needs_update = True
        else:
            # For EVERY other lifecycle status (pending, unverified, suspended, rejected, expired)
            if user.identity_verified:
                user.identity_verified = False
                needs_update = True

        if needs_update:
            user.save(update_fields=['identity_verified'])
            enhanced_sync_count += 1

    if enhanced_sync_count:
        print(f" [Migration 0019] Synchronized legacy Boolean for {enhanced_sync_count} enhanced_verified user(s).")

    # --- PART C: Correct Non-Qualifying Basic Records ---
    improperly_classified = User.objects.filter(assurance_level='basic_verified').exclude(qualifying_q)
    demoted_count = 0
    for user in improperly_classified:
        user.assurance_level = 'unverified'
        user.identity_verified = False

        # Only change status if current status was 'verified'
        # Explicitly preserves 'rejected', 'suspended', 'expired', 'pending'
        if user.id_verification_status == 'verified':
            user.id_verification_status = 'unverified'

        user.save(update_fields=['assurance_level', 'identity_verified', 'id_verification_status'])
        demoted_count += 1

    if demoted_count:
        print(f" [Migration 0019] Demoted {demoted_count} non-qualifying basic user(s) to 'unverified'.")


def prevent_unsafe_reverse(apps, schema_editor):
    """
    Explicitly irreversible to prevent rolling back into 0018's unsafe blanket reset.
    """
    raise IrreversibleError(
        "Migration 0019 is irreversible to protect database integrity and prevent "
        "an unsafe blanket reset of reviewed identity records."
    )


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0018_backfill_legacy_identity_assurance'),
    ]

    operations = [
        migrations.RunPython(
            correct_legacy_identity_assurance,
            reverse_code=prevent_unsafe_reverse
        ),
    ]
