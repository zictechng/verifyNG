
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_user_is_suspended'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='email',
            field=models.EmailField(
                max_length=254,
                unique=True,
                help_text='Required. Must be unique across all accounts.',
            ),
        ),
    ]