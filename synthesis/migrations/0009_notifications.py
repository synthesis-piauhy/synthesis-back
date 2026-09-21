import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("synthesis", "0008_guided_answers"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(max_length=32)),
                ("message", models.CharField(max_length=300)),
                ("href", models.CharField(max_length=255)),
                ("dedupe_key", models.CharField(max_length=160)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddConstraint(
            model_name="notification",
            constraint=models.UniqueConstraint(fields=("user", "dedupe_key"), name="notification_user_event_unique"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=("user", "read_at", "-created_at"), name="notif_user_read_date_idx"),
        ),
    ]
