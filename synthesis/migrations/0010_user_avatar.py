from django.db import migrations, models

import synthesis.validators


class Migration(migrations.Migration):
    dependencies = [("synthesis", "0009_notifications")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="avatar",
            field=models.ImageField(
                blank=True,
                upload_to="avatars/%Y/%m/",
                validators=[
                    synthesis.validators.validate_image_size,
                    synthesis.validators.validate_image_content_type,
                ],
            ),
        ),
    ]
