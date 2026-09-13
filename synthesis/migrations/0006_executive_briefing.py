from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("synthesis", "0005_activity_templates")]

    operations = [
        migrations.AddField(
            model_name="weeklyreport",
            name="executive_summary",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="reportsection",
            name="executive_summary",
            field=models.CharField(blank=True, max_length=180),
        ),
        migrations.AddField(
            model_name="reportcard",
            name="executive_classification",
            field=models.CharField(
                choices=[
                    ("informativo", "Informativo"),
                    ("destaque", "Destaque"),
                    ("atencao", "Ponto de atenção"),
                ],
                default="informativo",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="reportcard",
            name="needs_decision",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="reportcard",
            name="decision_request",
            field=models.CharField(blank=True, max_length=180),
        ),
        migrations.AddField(
            model_name="reportcard",
            name="next_step_owner",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="reportcard",
            name="next_step_due_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="reportcard",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("executive_classification__in", ["informativo", "destaque", "atencao"])
                ),
                name="card_executive_classification_valid",
            ),
        ),
    ]
