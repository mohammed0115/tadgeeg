"""
Rule Registry — loads and caches rule classes by dotted Python path.
Security: Only classes under ALLOWED_RULE_MODULES may be loaded.
"""
import importlib
import logging
from django.conf import settings

logger = logging.getLogger("rule_engine")

# Default: only load rule classes from the rule_engine app
DEFAULT_ALLOWED_MODULES = ["apps.rule_engine.rules"]


class RuleRegistryError(Exception):
    pass


class RuleRegistry:
    """Thread-safe rule class registry with module allowlist."""

    _cache: dict = {}

    def get_class(self, dotted_path: str):
        """
        Load and cache the rule class at `dotted_path`.
        Raises RuleRegistryError if path is not in allowed modules.
        """
        if dotted_path in self._cache:
            return self._cache[dotted_path]

        allowed_modules = getattr(settings, "ALLOWED_RULE_MODULES", DEFAULT_ALLOWED_MODULES)

        if not any(dotted_path.startswith(mod) for mod in allowed_modules):
            raise RuleRegistryError(
                f"Rule class '{dotted_path}' is not in ALLOWED_RULE_MODULES. "
                f"Allowed prefixes: {allowed_modules}"
            )

        try:
            module_path, class_name = dotted_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
        except (ImportError, AttributeError, ValueError) as e:
            raise RuleRegistryError(
                f"Cannot load rule class '{dotted_path}': {e}"
            ) from e

        logger.debug(f"Loaded rule class: {dotted_path}")
        self._cache[dotted_path] = cls
        return cls

    def clear_cache(self):
        """Clear the class cache (useful in tests)."""
        self._cache.clear()


# Module-level singleton
rule_registry = RuleRegistry()
