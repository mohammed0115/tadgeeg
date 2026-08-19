"""Structural guard: provider SDK construction belongs only to core.ai.gateway."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {ROOT / "core" / "ai" / "gateway.py"}


def _openai_imports(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "openai":
            if any(alias.name == "OpenAI" for alias in node.names):
                lines.append(node.lineno)
    return lines


def test_production_openai_client_is_constructed_only_by_the_usage_gateway():
    offenders: list[str] = []
    for base in (ROOT / "apps", ROOT / "core", ROOT / "finai_backend"):
        for path in base.rglob("*.py"):
            if "tests" in path.parts or path in ALLOWED:
                continue
            for line in _openai_imports(path):
                offenders.append(f"{path.relative_to(ROOT)}:{line}")
    assert not offenders, (
        "Direct OpenAI client imports bypass tenant usage accounting. "
        "Route the call through core.ai.gateway instead: " + ", ".join(offenders)
    )
