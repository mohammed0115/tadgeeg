from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0004_alter_invoice_cash_flow_class_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="vendorprofile",
            name="compliance_history",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="vendorprofile",
            name="compliance_issue_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="vendorprofile",
            name="high_risk_audit_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="vendorprofile",
            name="is_approved",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vendorprofile",
            name="last_audit_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vendorprofile",
            name="last_compliance_issue_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vendorprofile",
            name="last_transaction_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AddField(
            model_name="vendorprofile",
            name="risk_score",
            field=models.FloatField(default=0.0, help_text="Dynamic vendor risk score (0-100) derived from audit history."),
        ),
        migrations.AddField(
            model_name="vendorprofile",
            name="transaction_frequency_30d",
            field=models.FloatField(default=0.0, help_text="Recent document frequency for this vendor over the last 30 days."),
        ),
        migrations.AddField(
            model_name="vendorprofile",
            name="transaction_history",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterModelOptions(
            name="vendorprofile",
            options={"ordering": ["-risk_score", "-total_amount"]},
        ),
    ]
