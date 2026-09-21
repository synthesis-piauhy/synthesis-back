from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("synthesis", "0007_one_active_weekly_cycle")]

    operations = [
        migrations.AddField(
            model_name="activityreport",
            name="guided_answers",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
