# Generated manually for the invoice quota/audit identity bridge.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0013_canonical_data_organization"),
        ("invoices", "0016_chain_partition_and_fork_constraint"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="audit_document",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="+",
                to="documents.document",
            ),
        ),
    ]
