# users/migrations/0020_add_report_publishing_and_alternative_verification.py

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import core.storage

ACCEPTABLE_DOCS = {
    'nin', 'voters_card', 'passport', 'drivers_license',
    'ghana_card', 'cip', 'cni', 'national_id'
}

def populate_legacy_report_publishing_eligibility(apps, schema_editor):
    """
    Data migration: Grants can_publish_reports=True ONLY to qualifying legacy accounts
    matching all SIX strict criteria from Migration 0019:
      1. id_verification_status == 'verified'
      2. identity_verified == True
      3. id_type in ACCEPTABLE_DOCS (BVN strictly excluded)
      4. id_document is present and non-empty (id_document__gt='')
      5. id_verified_at is not null (id_verified_at__isnull=False)
      6. is_suspended == False
    """
    User = apps.get_model('users', 'User')
    qualifying = User.objects.filter(
        id_verification_status='verified',
        identity_verified=True,
        id_type__in=ACCEPTABLE_DOCS,
        id_document__gt='',
        id_verified_at__isnull=False,
        is_suspended=False
    )
    count = qualifying.update(can_publish_reports=True)
    if count:
        print(f" [Migration 0020] Granted report publishing eligibility to {count} qualifying legacy user(s).")

def reverse_legacy_report_publishing_eligibility(apps, schema_editor):
    User = apps.get_model('users', 'User')
    User.objects.filter(can_publish_reports=True).update(can_publish_reports=False)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0019_correct_legacy_identity_assurance'),
    ]

    operations = [
        # 1. Add can_publish_reports to User model
        migrations.AddField(
            model_name='user',
            name='can_publish_reports',
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text="Designates whether compliance has approved this user to publish community reports."
            ),
        ),
        # 2. Create AlternativeVerificationSubmission model
        migrations.CreateModel(
            name='AlternativeVerificationSubmission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('pending', 'Pending Compliance Review'), ('approved', 'Approved for Report Publishing'), ('rejected', 'Declined — Resubmission Allowed'), ('revoked', 'Revoked by Compliance')], db_index=True, default='pending', max_length=20)),
                ('evidence_type', models.CharField(choices=[('selfie_card', 'Manual Selfie Challenge with Date/Verification Card'), ('video_challenge', 'Recorded Video Prompt (Extensible)'), ('third_party_liveness', 'External Certified Liveness Check (Extensible)')], default='selfie_card', help_text='Format of personhood evidence submitted (manual review baseline)', max_length=30)),
                ('selfie_image', models.FileField(help_text='Selfie challenge image showing user holding handwritten verification card', storage=core.storage.PrivateEvidenceStorage(), upload_to='alternative_proofs/%Y/%m/')),
                ('supporting_document', models.FileField(blank=True, help_text='Optional non-ID proof of address, workplace letter, or utility bill', null=True, storage=core.storage.PrivateEvidenceStorage(), upload_to='alternative_proofs/%Y/%m/')),
                ('residential_country', models.CharField(help_text='ISO-2 country code of physical residence', max_length=2)),
                ('residential_address', models.TextField(help_text='Declared physical residential address')),
                ('declaration_statement', models.TextField(blank=True, default='', help_text='Applicant statement confirming truthfulness of identity')),
                ('submitted_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('rejection_reason', models.TextField(blank=True, default='', help_text='Feedback provided by compliance officer if declined')),
                ('reviewed_by', models.ForeignKey(blank=True, help_text='Compliance officer who evaluated the submission', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='alternative_verifications_reviewed', to='users.user')),
                ('user', models.ForeignKey(help_text='Applicant account', on_delete=django.db.models.deletion.CASCADE, related_name='alternative_verification_submissions', to='users.user')),
            ],
            options={
                'verbose_name': 'Alternative Verification Submission',
                'verbose_name_plural': 'Alternative Verification Submissions',
                'ordering': ['-submitted_at', '-id'],
            },
        ),
        # 3. Synchronize Qualifying Legacy Accounts
        migrations.RunPython(
            populate_legacy_report_publishing_eligibility,
            reverse_legacy_report_publishing_eligibility
        ),
    ]
