
# users/migrations/0008_user_service_access.py

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0007_user_email_unique'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserServiceAccess',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('service', models.CharField(
                    max_length=30,
                    choices=[
                        ('check',        'Search / Check'),
                        ('fraud_report', 'Fraud Reporting'),
                        ('verification', 'Identity Verification'),
                        ('certificate',  'Certificate Application'),
                    ],
                    db_index=True,
                )),
                ('is_restricted', models.BooleanField(default=False)),
                ('restricted_at', models.DateTimeField(null=True, blank=True)),
                ('reason', models.TextField(blank=True, default='')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('restricted_by', models.ForeignKey(
                    settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.SET_NULL,
                    null=True, blank=True,
                    related_name='service_restrictions_applied',
                )),
                ('user', models.ForeignKey(
                    settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='service_access_rules',
                )),
            ],
            options={
                'verbose_name': 'User Service Access',
                'verbose_name_plural': 'User Service Access Rules',
                'ordering': ['user', 'service'],
            },
        ),
        migrations.AddConstraint(
            model_name='userserviceaccess',
            constraint=models.UniqueConstraint(
                fields=['user', 'service'],
                name='unique_user_service',
            ),
        ),
    ]
