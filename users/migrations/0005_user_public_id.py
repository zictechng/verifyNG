from django.db import migrations, models
import uuid


def assign_public_ids(apps, schema_editor):
    """Assign a unique UUID to every existing user row."""
    User = apps.get_model('users', 'User')
    for user in User.objects.all():
        user.public_id = uuid.uuid4()
        user.save(update_fields=['public_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0004_rename_is_verified'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='public_id',
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(assign_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='user',
            name='public_id',
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                unique=True,
                db_index=True,
                help_text="Public-facing user identifier — never expose the integer PK"
            ),
        ),
    ]