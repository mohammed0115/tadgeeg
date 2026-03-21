import logging
from apps.rule_engine.rules.base import NormalizedDocument
from apps.rule_engine.normalizers import BaseNormalizer, DocumentNormalizerFactory

logger = logging.getLogger("rule_engine")


class FixedAssetNormalizer(BaseNormalizer):
    document_type = "fixed_asset"

    def normalize(self, document_id: str, organization_id: str) -> NormalizedDocument:
        from apps.documents.typed_models import FixedAsset
        try:
            asset_reg = FixedAsset.objects.get(id=document_id)
        except FixedAsset.DoesNotExist:
            logger.warning(f"FixedAsset {document_id} not found")
            return NormalizedDocument(
                document_id=str(document_id),
                document_type="fixed_asset",
                organization_id=str(organization_id),
            )

        assets = asset_reg.assets or []
        typed_data = {
            "company_name": asset_reg.company_name,
            "department": asset_reg.department,
            "fiscal_year": asset_reg.fiscal_year,
            "register_date": str(asset_reg.register_date) if asset_reg.register_date else None,
            "total_cost": float(asset_reg.total_cost) if asset_reg.total_cost is not None else None,
            "total_accumulated_depreciation": float(asset_reg.total_accumulated_depreciation) if asset_reg.total_accumulated_depreciation is not None else None,
            "total_book_value": float(asset_reg.total_book_value) if asset_reg.total_book_value is not None else None,
            "asset_count": asset_reg.asset_count,
            "assets": assets,
            # Flags
            "negative_book_value_count": asset_reg.negative_book_value_count,
            "over_depreciated_count": asset_reg.over_depreciated_count,
            "wrong_depreciation_rate": asset_reg.wrong_depreciation_rate or [],
            "missing_asset_id_count": asset_reg.missing_asset_id_count,
            "duplicate_asset_id_count": asset_reg.duplicate_asset_id_count,
        }

        return NormalizedDocument(
            document_id=str(document_id),
            document_type="fixed_asset",
            organization_id=str(organization_id),
            document_number=asset_reg.fiscal_year,
            total_amount=float(asset_reg.total_book_value) if asset_reg.total_book_value is not None else None,
            counterparty_name=asset_reg.company_name,
            typed_data=typed_data,
            org_context=self._get_org_context(organization_id),
        )


DocumentNormalizerFactory.register("fixed_asset", FixedAssetNormalizer)
