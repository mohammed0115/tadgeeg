from unittest.mock import Mock

from apps.storage_management.services.storage.backends.s3 import S3StorageBackend


def test_presigned_download_url_caps_expiry_at_five_minutes(monkeypatch):
    backend = S3StorageBackend(bucket="test-bucket")
    client = Mock()
    client.generate_presigned_url.return_value = "https://example.test/signed"
    monkeypatch.setattr(backend, "_get_client", lambda: client)

    backend.generate_download_url("org/file.pdf", expires_in=86400)

    assert client.generate_presigned_url.call_args.kwargs["ExpiresIn"] == 300


def test_presigned_download_url_requires_positive_expiry(monkeypatch):
    backend = S3StorageBackend(bucket="test-bucket")
    client = Mock()
    client.generate_presigned_url.return_value = "https://example.test/signed"
    monkeypatch.setattr(backend, "_get_client", lambda: client)

    backend.generate_download_url("org/file.pdf", expires_in=0)

    assert client.generate_presigned_url.call_args.kwargs["ExpiresIn"] == 1
