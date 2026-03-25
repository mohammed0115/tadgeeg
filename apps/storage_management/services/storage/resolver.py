"""
StorageResolver — maps an organisation + purpose to a concrete backend instance.
"""
import logging
from pathlib import Path

from django.conf import settings

from apps.storage_management.exceptions import StorageConfigurationError
from apps.storage_management.models import (
    OrganizationStoragePolicy,
    StorageConfig,
    StorageProvider,
)
from apps.storage_management.utils.encryption import decrypt_value

logger = logging.getLogger(__name__)


class StorageResolver:
    """
    Resolves the correct storage backend for a given organisation and purpose.

    Resolution order:
        1. Organisation-specific policy (OrganizationStoragePolicy).
        2. Global default provider (StorageProvider.is_default=True).
        3. Raise StorageConfigurationError if neither exists.
    """

    PURPOSE_FIELD_MAP = {
        "upload": "primary_storage",
        "backup": "backup_storage",
        "archive": "archive_storage",
        "temp": "temp_storage",
    }

    def get_provider(self, organization, purpose: str = "upload") -> StorageProvider:
        """
        Return the StorageProvider for the given organisation and purpose.

        Args:
            organization: An Organisation model instance.
            purpose: One of 'upload', 'backup', 'archive', 'temp'.

        Returns:
            A StorageProvider instance.

        Raises:
            StorageConfigurationError: if no provider can be resolved.
        """
        field = self.PURPOSE_FIELD_MAP.get(purpose, "primary_storage")

        # 1. Organisation-specific policy
        try:
            policy = OrganizationStoragePolicy.objects.select_related(
                "primary_storage",
                "backup_storage",
                "archive_storage",
                "temp_storage",
            ).get(organization=organization)
            provider = getattr(policy, field, None)
            if provider and provider.is_active:
                return provider
            # Fall back to primary if the requested purpose slot is empty
            if policy.primary_storage and policy.primary_storage.is_active:
                logger.info(
                    "Storage purpose '%s' not configured for org %s; falling back to primary.",
                    purpose,
                    organization.id,
                )
                return policy.primary_storage
        except OrganizationStoragePolicy.DoesNotExist:
            pass

        # 2. Global default provider
        try:
            return StorageProvider.objects.get(is_default=True, is_active=True)
        except StorageProvider.DoesNotExist:
            pass

        raise StorageConfigurationError(
            f"No active storage provider found for organisation '{organization}' "
            f"and purpose '{purpose}'. Configure an OrganizationStoragePolicy or "
            f"mark a provider as the global default."
        )

    def get_backend(self, organization, purpose: str = "upload"):
        """
        Return an instantiated, ready-to-use storage backend.

        Args:
            organization: An Organisation model instance.
            purpose: Storage purpose.

        Returns:
            A concrete BaseStorageBackend instance.
        """
        provider = self.get_provider(organization, purpose)
        return self._build_backend(provider)

    def _build_backend(self, provider: StorageProvider):
        """
        Instantiate the correct backend class for the given provider.

        Args:
            provider: A StorageProvider model instance.

        Returns:
            A concrete BaseStorageBackend instance.

        Raises:
            StorageConfigurationError: for unsupported/unconfigured provider types.
        """
        from apps.storage_management.services.storage.backends.local import LocalStorageBackend
        from apps.storage_management.services.storage.backends.s3 import S3StorageBackend
        from apps.storage_management.services.storage.backends.minio import MinIOStorageBackend

        # Attempt to load config (may not exist for minimal setups)
        config = None
        try:
            config = StorageConfig.objects.get(provider=provider)
        except StorageConfig.DoesNotExist:
            pass

        provider_type = provider.provider_type

        if provider_type == StorageProvider.ProviderType.LOCAL:
            base_path = None
            if config and config.base_path:
                base_path = config.base_path
            else:
                base_path = str(Path(settings.MEDIA_ROOT) / "storage")
            return LocalStorageBackend(base_path=base_path)

        if provider_type == StorageProvider.ProviderType.S3:
            if not config:
                raise StorageConfigurationError(
                    f"StorageConfig missing for S3 provider '{provider.name}'."
                )
            return S3StorageBackend(
                bucket=config.bucket_name,
                region=config.region or "us-east-1",
                access_key=decrypt_value(config.access_key_encrypted),
                secret_key=decrypt_value(config.secret_key_encrypted),
                endpoint_url=config.endpoint_url or "",
                use_ssl=config.use_ssl,
            )

        if provider_type == StorageProvider.ProviderType.MINIO:
            if not config:
                raise StorageConfigurationError(
                    f"StorageConfig missing for MinIO provider '{provider.name}'."
                )
            if not config.endpoint_url:
                raise StorageConfigurationError(
                    f"MinIO provider '{provider.name}' requires an endpoint_url in its StorageConfig."
                )
            return MinIOStorageBackend(
                bucket=config.bucket_name,
                endpoint_url=config.endpoint_url,
                region=config.region or "us-east-1",
                access_key=decrypt_value(config.access_key_encrypted),
                secret_key=decrypt_value(config.secret_key_encrypted),
                use_ssl=config.use_ssl,
            )

        if provider_type == StorageProvider.ProviderType.AZURE:
            raise StorageConfigurationError(
                "Azure Blob Storage backend is not yet implemented."
            )

        raise StorageConfigurationError(
            f"Unknown provider type '{provider_type}' for provider '{provider.name}'."
        )
