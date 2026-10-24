from django.db import migrations, models
import uuid


def assign_public_ids(apps, schema_editor):
    """Assign a unique UUID to every existing VerificationRequest and VerificationCertificate."""
    VerificationRequest = apps.get_model('verification', 'VerificationRequest')
    VerificationCertificate = apps.get_model('verification', 'VerificationCertificate')
    for req in VerificationRequest.objects.all():
        req.public_id = uuid.uuid4()
        req.save(update_fields=['public_id'])
    for cert in VerificationCertificate.objects.all():
        cert.public_id = uuid.uuid4()
        cert.save(update_fields=['public_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('verification', '0006_verificationrequest_document_verificationdocument'),
    ]

    operations = [
        migrations.AddField(
            model_name='verificationrequest',
            name='public_id',
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.AddField(
            model_name='verificationcertificate',
            name='public_id',
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(assign_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='verificationrequest',
            name='public_id',
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                unique=True,
                db_index=True,
                help_text="Public-facing verification request identifier — never expose the integer PK"
            ),
        ),
        migrations.AlterField(
            model_name='verificationcertificate',
            name='public_id',
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                unique=True,
                db_index=True,
                help_text="Public-facing certificate identifier — never expose the integer PK"
            ),
        ),
    ]
