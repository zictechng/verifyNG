
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('identities', '0003_trust_score_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='subjectentity',
            name='photo',
            field=models.ImageField(
                blank=True,
                help_text='Optional photo of the subject. Displayed on report detail page.',
                null=True,
                upload_to='subjects/photos/',
            ),
        ),
    ]

