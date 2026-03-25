# Generated migration to add missing fields to Invoice model

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0002_invoice_audit_session_invoicebatch_audit_session'),
    ]

    operations = [
        # QR Code fields
        migrations.AddField(
            model_name='invoice',
            name='qr_code_image',
            field=models.TextField(blank=True, default='', help_text='Base64-encoded QR code image'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='invoice',
            name='qr_code_data',
            field=models.TextField(blank=True, default='', help_text='Base64-encoded TLV data from QR code'),
            preserve_default=False,
        ),
        
        # Soft delete fields
        migrations.AddField(
            model_name='invoice',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='invoice',
            name='deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='invoice',
            name='deleted_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='deleted_invoices', to='authentication.user'),
        ),
        
        # IAS 7 Cash Flow Classification fields
        migrations.AddField(
            model_name='invoice',
            name='cash_flow_class',
            field=models.CharField(blank=True, choices=[('operating', 'Operating Activities'), ('investing', 'Investing Activities'), ('financing', 'Financing Activities'), ('unknown', 'Unknown')], default='unknown', max_length=20),
        ),
        migrations.AddField(
            model_name='invoice',
            name='cash_flow_subcategory',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='invoice',
            name='cash_flow_confidence',
            field=models.FloatField(blank=True, null=True, help_text='Confidence score (0-1) for cash flow classification'),
        ),
        migrations.AddField(
            model_name='invoice',
            name='cash_flow_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='invoice',
            name='cash_flow_verified_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='verified_invoice_cash_flows', to='authentication.user'),
        ),
        migrations.AddField(
            model_name='invoice',
            name='cash_flow_verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
