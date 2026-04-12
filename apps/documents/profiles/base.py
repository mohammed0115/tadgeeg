from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(slots=True)
class DocumentFieldSpec:
    key: str
    label_ar: str
    label_en: str
    data_type: str
    required: bool
    nullable: bool = False
    computed: bool = False
    ui_section: str = "general"
    ui_order: int = 0


class DocumentTypeProfile(ABC):
    code: str
    name_ar: str
    name_en: str
    category: str
    fields: list[DocumentFieldSpec]
    blocking_rule_codes: list[str]
    workflow_states: list[str]
    approval_levels: int = 1
    high_value_threshold: Optional[Decimal] = None

    def get_required_fields(self) -> list[str]:
        return [field.key for field in self.fields if field.required]

    def get_optional_fields(self) -> list[str]:
        return [field.key for field in self.fields if not field.required]

    def validate_completeness(self, data: dict) -> list[str]:
        missing: list[str] = []
        for key in self.get_required_fields():
            value = data.get(key)
            if value is None or value == "" or value == []:
                missing.append(key)
        return missing


def build_field(
    key: str,
    label_ar: str,
    label_en: str,
    data_type: str,
    required: bool,
    *,
    nullable: bool = False,
    computed: bool = False,
    ui_section: str = "general",
    ui_order: int = 0,
) -> DocumentFieldSpec:
    return DocumentFieldSpec(
        key=key,
        label_ar=label_ar,
        label_en=label_en,
        data_type=data_type,
        required=required,
        nullable=nullable,
        computed=computed,
        ui_section=ui_section,
        ui_order=ui_order,
    )