from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("synthesis", "0006_executive_briefing")]

    operations = [
        migrations.AddConstraint(
            model_name="weeklycycle",
            constraint=models.UniqueConstraint(
                models.Value(1),
                condition=models.Q(status__in=("aberta", "reaberta")),
                name="one_active_weekly_cycle",
            ),
        ),
    ]
