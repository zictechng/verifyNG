
# employer/migrations/0003_team_invite.py
import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('employer', '0002_staff_check_request_monitor'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TeamInvite',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('email', models.EmailField(db_index=True, max_length=254)),
                ('team_role', models.CharField(
                    choices=[('admin', 'Team Admin'), ('checker', 'Checker'), ('viewer', 'Viewer')],
                    default='checker',
                    max_length=20,
                )),
                ('token', models.CharField(db_index=True, max_length=64, unique=True)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending — not yet accepted'),
                        ('accepted', 'Accepted'),
                        ('expired', 'Expired'),
                        ('revoked', 'Revoked'),
                    ],
                    db_index=True,
                    default='pending',
                    max_length=20,
                )),
                ('expires_at', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('employer', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='invitations',
                    to='employer.employerprofile',
                )),
                ('invited_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='invitations_sent',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('accepted_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='invitations_accepted',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Team Invitation',
                'verbose_name_plural': 'Team Invitations',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='teaminvite',
            index=models.Index(fields=['employer', 'status'], name='employer_ti_employer_status_idx'),
        ),
    ]
    