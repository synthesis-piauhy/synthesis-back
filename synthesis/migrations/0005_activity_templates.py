from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("synthesis", "0004_session_security")]

    operations = [
        migrations.AddField(
            model_name="activityreport",
            name="template_key",
            field=models.CharField(
                choices=[
                    ("legado", "Relato legado"),
                    ("acao_evento", "Ação ou evento realizado"),
                    ("entrega_marco", "Entrega ou marco concluído"),
                    ("atendimento_articulacao", "Atendimento ou articulação"),
                ],
                default="legado",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="activityreport",
            name="template_version",
            field=models.PositiveSmallIntegerField(default=1, editable=False),
        ),
        migrations.AddField(
            model_name="activityreport",
            name="evidence",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="activityreport",
            name="next_step",
            field=models.CharField(blank=True, max_length=140),
        ),
        migrations.AddField(
            model_name="activityreport",
            name="internal_notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="reportcard",
            name="editorial_evidence",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="reportcard",
            name="editorial_next_step",
            field=models.CharField(blank=True, max_length=140),
        ),
        migrations.AddConstraint(
            model_name="activityreport",
            constraint=models.CheckConstraint(
                condition=models.Q(("template_version__gte", 1)),
                name="activity_template_version_positive",
            ),
        ),
    ]
