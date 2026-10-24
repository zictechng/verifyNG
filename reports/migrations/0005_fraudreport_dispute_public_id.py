from django.db import migrations, models
import uuid


def assign_public_ids(apps, schema_editor):
    """Assign a unique UUID to every existing FraudReport and Dispute."""
    FraudReport = apps.get_model('reports', 'FraudReport')
    Dispute = apps.get_model('reports', 'Dispute')
    for r in FraudReport.objects.all():
        r.public_id = uuid.uuid4()
        r.save(update_fields=['public_id'])
    for d in Dispute.objects.all():
        d.public_id = uuid.uuid4()
        d.save(update_fields=['public_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0004_auditlog_extend'),
    ]

    operations = [
        migrations.AddField(
            model_name='fraudreport',
            name='public_id',
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.AddField(
            model_name='dispute',
            name='public_id',
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(assign_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='fraudreport',
            name='public_id',
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                unique=True,
                db_index=True,
                help_text="Public-facing report identifier — never expose the integer PK"
            ),
        ),
        migrations.AlterField(
            model_name='dispute',
            name='public_id',
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                unique=True,
                db_index=True,
                help_text="Public-facing dispute identifier — never expose the integer PK"
            ),
        ),
    ]
