#!/usr/bin/env python3
"""Report API view classes that access user organization without a membership guard.

This is a conservative review aid, not a security exemption engine. It prints
classes that should be reviewed; all hits must be resolved intentionally.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def name_of(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = name_of(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.List | ast.Tuple):
        return ",".join(name_of(item) for item in node.elts)
    return ""


def class_has_org_access(node: ast.ClassDef) -> bool:
    text = ast.unparse(node)
    markers = (
        "request.user.organization",
        "request.user.organization_id",
        "getattr(request.user, 'organization'",
        'getattr(request.user, "organization"',
        "self.request.user.organization",
    )
    return any(marker in text for marker in markers)


def class_has_guard(node: ast.ClassDef) -> bool:
    text = ast.unparse(node)
    return "IsOrganizationMember" in text or "org_member_required" in text


def class_is_api_view(node: ast.ClassDef) -> bool:
    return any("APIView" in name_of(base) or "ViewSet" in name_of(base) for base in node.bases)


for path in sorted((ROOT / "apps").rglob("*.py")):
    if "migrations" in path.parts or "tests" in path.parts:
        continue
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not class_is_api_view(node):
            continue
        if class_has_org_access(node) and not class_has_guard(node):
            print(f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}")
