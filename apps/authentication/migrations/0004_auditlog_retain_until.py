from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0003_user_email_verified_at_emailotpverification"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditlog",
            name="retain_until",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="Records are retained until this date (7-year minimum per regulatory requirements).",
                null=True,
            ),
        ),
    ]
