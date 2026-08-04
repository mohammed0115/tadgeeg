"""Freeze the chain partition, then make a forked chain impossible.

The constraint is the point of this migration; `chain_partition` exists so the
constraint can be written at all. Ordering inside `operations` is therefore
load-bearing and the backfill below is not optional:

  1. add the columns
  2. **backfill** — every existing row still has chain_partition="" here, and
     each organisation's chain independently starts at position 1. Adding the
     unique constraint before this step would compare ("", 1) from one tenant
     against ("", 1) from every other and fail on the first multi-tenant
     database it touched.
  3. null out positions on unchained rows — they all carry 0 today, and 0 is a
     value, so N unchained rows in one partition are N copies of (p, 0). NULL
     is the only "no position" that a unique index ignores.
  4. add the index, then the constraint

`chain_actor` is backfilled from the FK, which is the best available source:
for any row whose user has already been deleted the id is gone, and the
snapshot honestly records that rather than inventing one.
"""

from django.db import migrations, models


def freeze_partitions(apps, schema_editor):
    AuditLog = apps.get_model("authentication", "AuditLog")

    # Matches HashChainMixin.compute_hash's partition string exactly:
    # str(organization_id or ""). Any divergence and every pre-existing row
    # fails verification.
    for organization_id in (
        AuditLog.objects.order_by().values_list("organization_id", flat=True).distinct()
    ):
        AuditLog.objects.filter(organization_id=organization_id).update(
            chain_partition=str(organization_id or "")
        )

    AuditLog.objects.filter(chain_actor="", user_id__isnull=False).update(
        chain_actor=models.F("user_id")
    )
    # A row with no event_hash was never chained; 0 claimed otherwise.
    AuditLog.objects.filter(event_hash="").update(chain_position=None)


def unfreeze_partitions(apps, schema_editor):
    AuditLog = apps.get_model("authentication", "AuditLog")
    AuditLog.objects.filter(chain_position__isnull=True).update(chain_position=0)
    AuditLog.objects.update(chain_partition="", chain_actor="")


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0010_rebuild_audit_log_chains'),
    ]

    operations = [
        migrations.AddField(
            model_name='auditlog',
            name='chain_actor',
            field=models.CharField(blank=True, default='', help_text='user id frozen at write time; survives user deletion', max_length=64),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='chain_partition',
            field=models.CharField(blank=True, db_index=True, default='', help_text="Frozen partition key (organization id) this row's chain belongs to", max_length=64),
        ),
        migrations.AlterField(
            model_name='auditlog',
            name='chain_position',
            field=models.PositiveBigIntegerField(blank=True, db_index=True, default=None, help_text='1-based position within this chain; NULL until chained', null=True),
        ),
        migrations.AlterField(
            model_name='auditlog',
            name='event_hash',
            field=models.CharField(blank=True, db_index=True, default='', help_text='SHA-256(previous_hash + payload + partition)', max_length=64),
        ),
        migrations.AlterField(
            model_name='auditlog',
            name='previous_hash',
            field=models.CharField(blank=True, default='', help_text='event_hash of the previous row in this chain', max_length=64),
        ),
        # Must run before AddConstraint — see the module docstring.
        migrations.RunPython(freeze_partitions, unfreeze_partitions),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['chain_partition', 'chain_position'], name='auditlog_chain_idx'),
        ),
        migrations.AddConstraint(
            model_name='auditlog',
            constraint=models.UniqueConstraint(fields=('chain_partition', 'chain_position'), name='uniq_chain_position_auditlog'),
        ),
    ]
