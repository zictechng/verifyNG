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
        ('users', '0004_rename_is_verified'),  # ← keep your actual previous migration name
    ]

    operations = [
        # Step 1: add the column WITHOUT the unique constraint, nullable so existing rows don't conflict
        migrations.AddField(
            model_name='user',
            name='public_id',
            field=models.UUIDField(null=True, editable=False),
        ),
        # Step 2: populate every existing row with its own fresh UUID
        migrations.RunPython(assign_public_ids, migrations.RunPython.noop),
        # Step 3: now enforce unique + not null
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