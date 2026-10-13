
# Generated manually — adds is_suspended to the User model
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0005_user_public_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='is_suspended',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'Suspended users can still log in but cannot perform any '
                    'platform actions. Use is_active=False to fully block login.'
                ),
            ),
        ),
    ]
    