from django.db import migrations


SETTING_KEY = "whatsapp_business_number"


def seed_whatsapp_business_number(apps, schema_editor):
    PlatformSetting = apps.get_model("cms", "PlatformSetting")
    PlatformSetting.objects.get_or_create(
        key=SETTING_KEY,
        defaults={
            "value": "",
            "group": "contact",
            "label": "WhatsApp Business Number",
            "description": "Public business contact number in E.164 format; not Meta phone-number ID or access token.",
            "is_public": False,
            "value_type": "text",
        },
    )


class Migration(migrations.Migration):
    dependencies = [("cms", "0001_initial")]

    operations = [
        migrations.RunPython(seed_whatsapp_business_number, migrations.RunPython.noop),
    ]
