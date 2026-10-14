
# reports/migrations/0004_auditlog_extend.py

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0003_add_evidence_storage_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='auditlog',
            name='action_type',
            field=models.CharField(
                max_length=30,
                default='GENERAL',
                choices=[
                    ('AUTH',        'Authentication'),
                    ('USER_MGMT',   'User Management'),
                    ('REPORT',      'Fraud Report'),
                    ('VERIFICATION','Verification'),
                    ('PAYMENT',     'Payment'),
                    ('ADMIN',       'Admin Action'),
                    ('SYSTEM',      'System Event'),
                    ('GENERAL',     'General'),
                ],
                db_index=True,
            ),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='target_user',
            field=models.ForeignKey(
                settings.AUTH_USER_MODEL,
                on_delete=django.db.models.deletion.SET_NULL,
                null=True,
                blank=True,
                related_name='audit_logs_as_target',
            ),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='url_path',
            field=models.CharField(max_length=500, blank=True, default=''),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='http_method',
            field=models.CharField(max_length=10, blank=True, default=''),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='user_agent',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='device_type',
            field=models.CharField(max_length=50, blank=True, default=''),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='browser',
            field=models.CharField(max_length=80, blank=True, default=''),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='os',
            field=models.CharField(max_length=80, blank=True, default=''),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='location_country',
            field=models.CharField(max_length=100, blank=True, default=''),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='location_city',
            field=models.CharField(max_length=100, blank=True, default=''),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['action_type', 'timestamp'], name='auditlog_type_ts_idx'),
        ),
    ]

    