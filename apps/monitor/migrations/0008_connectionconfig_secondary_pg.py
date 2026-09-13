from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0007_appversion'),
    ]

    operations = [
        migrations.AddField(
            model_name='connectionconfig',
            name='pg_secondary_host',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='connectionconfig',
            name='pg_secondary_name',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='connectionconfig',
            name='pg_secondary_password',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='connectionconfig',
            name='pg_secondary_port',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='connectionconfig',
            name='pg_secondary_user',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
