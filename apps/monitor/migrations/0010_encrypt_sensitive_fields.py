from django.db import migrations, models

from apps.monitor import security as secret_security


def encrypt_existing_secrets(apps, schema_editor):
    stores = [
        ("monitor", "aiconfig", ["api_key"]),
        ("monitor", "connectionconfig", [
            "pg_password",
            "pg_secondary_password",
            "redis_url",
            "ai_api_key",
        ]),
        ("monitor_accounts", "monitorprofile", ["apotek_access", "apotek_refresh"]),
    ]
    for app_label, model_name, fields in stores:
        model = apps.get_model(app_label, model_name)
        for row in model.objects.only(*fields).iterator():
            updates = {}
            for field in fields:
                value = getattr(row, field)
                if value and not secret_security.is_encrypted(value):
                    updates[field] = secret_security.encrypt_secret(value)
            if updates:
                model.objects.filter(pk=row.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0009_maintenancemode"),
    ]

    operations = [
        migrations.AlterField(
            model_name="aiconfig",
            name="api_key",
            field=models.CharField(blank=True, default="", max_length=512),
        ),
        migrations.AlterField(
            model_name="connectionconfig",
            name="pg_password",
            field=models.CharField(blank=True, default="", max_length=512),
        ),
        migrations.AlterField(
            model_name="connectionconfig",
            name="pg_secondary_password",
            field=models.CharField(blank=True, default="", max_length=512),
        ),
        migrations.AlterField(
            model_name="connectionconfig",
            name="redis_url",
            field=models.CharField(
                blank=True,
                default="",
                help_text="redis://[:password@]host:port/db — kosongkan untuk default.",
                max_length=1024,
            ),
        ),
        migrations.RunPython(encrypt_existing_secrets, migrations.RunPython.noop),
    ]
