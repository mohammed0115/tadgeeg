"""
Pytest Configuration & Shared Fixtures

Provides:
- Django/Celery test setup
- Database fixtures
- Authentication fixtures
- Mock external services
- Common test utilities
"""

import os
from unittest.mock import Mock, patch

import pytest
from django.conf import settings
from django.test import Client
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "finai_backend.settings")


# ─── Test Database Configuration ──────────────────────────────────────────────

# ─── Organizations & Authentication ──────────────────────────────────────────

@pytest.fixture
def organization(db):
    """Create a test organization"""
    from apps.authentication.models import Organization

    return Organization.objects.create(
        name="Test Organization",
        name_ar="منظمة الاختبار",
        country=Organization.Country.SAUDI_ARABIA,
        currency=Organization.Currency.SAR,
        vat_number="300000000000003",
    )


@pytest.fixture
def admin_user(db, organization):
    """Create admin user"""
    User = get_user_model()

    return User.objects.create_user(
        email="admin@test.finai",
        password="TestPass123!",
        full_name="Admin User",
        role=User.Role.ADMIN,
        organization=organization,
        is_staff=True,
    )


@pytest.fixture
def auditor_user(db, organization):
    """Create senior auditor user"""
    User = get_user_model()

    return User.objects.create_user(
        email="auditor@test.finai",
        password="TestPass123!",
        full_name="Senior Auditor",
        role=User.Role.SENIOR_AUDITOR,
        organization=organization,
    )


@pytest.fixture
def junior_auditor(db, organization):
    """Create junior auditor user"""
    User = get_user_model()

    return User.objects.create_user(
        email="junior@test.finai",
        password="TestPass123!",
        full_name="Junior Auditor",
        role=User.Role.JUNIOR_AUDITOR,
        organization=organization,
    )


@pytest.fixture
def finance_manager(db, organization):
    """Create finance manager user"""
    User = get_user_model()

    return User.objects.create_user(
        email="finance@test.finai",
        password="TestPass123!",
        full_name="Finance Manager",
        role=User.Role.FINANCE_MANAGER,
        organization=organization,
    )


# ─── API Clients ────────────────────────────────────────────────────────────

@pytest.fixture
def api_client():
    """Unauthenticated API client"""
    return APIClient()


@pytest.fixture
def authenticated_client(api_client, auditor_user):
    """Authenticated API client as auditor"""
    api_client.force_authenticate(user=auditor_user)
    return api_client


@pytest.fixture
def admin_client(api_client, admin_user):
    """Authenticated API client as admin"""
    api_client.force_authenticate(user=admin_user)
    return api_client


@pytest.fixture
def web_client():
    """Django web client for template testing"""
    return Client()


# ─── Documents & Invoices Fixtures ──────────────────────────────────────────

@pytest.fixture
def document(db, organization, admin_user):
    """Create a test document"""
    from apps.documents.models import Document

    return Document.objects.create(
        organization=organization,
        uploaded_by=admin_user,
        original_filename="test_invoice.pdf",
        file="path/to/test.pdf",
        file_size=102400,  # 100 KB
        mime_type="application/pdf",
        document_type=Document.DocumentType.INVOICE,
        processing_status=Document.ProcessingStatus.PENDING,
    )


@pytest.fixture
def invoice(db, organization, admin_user):
    """Create a test invoice"""
    from decimal import Decimal
    from datetime import date
    from apps.invoices.models import Invoice
    
    return Invoice.objects.create(
        organization=organization,
        uploaded_by=admin_user,
        original_filename="invoice_001.pdf",
        invoice_number="INV-001",
        invoice_date=date(2026, 3, 15),
        vendor_name="Test Vendor",
        vendor_vat_number="300000000000010",
        currency=Invoice.Currency.SAR,
        subtotal=Decimal("1000.00"),
        vat_amount=Decimal("150.00"),
        total_amount=Decimal("1150.00"),
        status=Invoice.Status.PENDING,
    )


@pytest.fixture
def transaction(db, organization):
    """Create a test transaction"""
    from decimal import Decimal
    from datetime import date
    from apps.transactions.models import Transaction
    
    return Transaction.objects.create(
        organization=organization,
        transaction_type=Transaction.TransactionType.EXPENSE,
        amount=Decimal("1150.00"),
        currency=organization.currency,
        vat_amount=Decimal("150.00"),
        vendor_name="Test Vendor",
        invoice_number="INV-001",
        transaction_date=date(2026, 3, 15),
        description="Test transaction",
    )


# ─── Mock External Services ─────────────────────────────────────────────────

@pytest.fixture
def mock_openai():
    """Mock OpenAI API client"""
    with patch('core.services.ai.openai_extractor.OpenAI') as mock:
        client = Mock()
        response = Mock()
        response.choices[0].message.content = '{"document_type": "invoice", "confidence": 0.95}'
        client.chat.completions.create.return_value = response
        mock.return_value = client
        yield mock


@pytest.fixture
def mock_tesseract():
    """Mock Tesseract OCR"""
    with patch('pytesseract.image_to_string') as mock:
        mock.return_value = "Sample OCR text from image"
        yield mock


@pytest.fixture
def mock_circuit_breaker():
    """Mock circuit breaker to always be CLOSED"""
    with patch('core.utils.circuit_breaker.OPENAI_CIRCUIT_BREAKER') as mock:
        mock.state = 'CLOSED'
        mock.call = Mock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs))
        yield mock


# ─── Celery Task Fixtures ─────────────────────────────────────────────────

@pytest.fixture
def celery_always_eager():
    """Configure Celery to run tasks synchronously in tests"""
    settings.CELERY_ALWAYS_EAGER = True
    settings.CELERY_EAGER_PROPAGATES_EXCEPTIONS = True
    yield
    settings.CELERY_ALWAYS_EAGER = False
    settings.CELERY_EAGER_PROPAGATES_EXCEPTIONS = False


# ─── File Upload Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def sample_pdf_file(tmp_path):
    """Create a mock PDF file"""
    pdf_content = b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n'  # PDF magic bytes
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(pdf_content)
    return pdf_file


@pytest.fixture
def sample_image_file(tmp_path, admin_user):
    """Create a mock image file"""
    # PNG magic bytes
    png_content = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
    img_file = tmp_path / "test.png"
    img_file.write_bytes(png_content)
    return img_file


@pytest.fixture
def malicious_exe_file(tmp_path):
    """Create a mock executable file (for security testing)"""
    exe_content = b'MZ\x90\x00'  # PE executable signature
    exe_file = tmp_path / "malicious.exe"
    exe_file.write_bytes(exe_content)
    return exe_file


@pytest.fixture
def zip_bombs_file(tmp_path):
    """Create a ZIP bomb file for testing"""
    import zipfile
    zip_file = tmp_path / "bomb.zip"
    
    with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Create highly compressible data
        data = b'A' * 1000000  # 1MB of same character
        zf.writestr("file.txt", data, compress_type=zipfile.ZIP_DEFLATED)
    
    return zip_file


# ─── Test Data Builders ────────────────────────────────────────────────────

@pytest.fixture
def invoice_factory(organization, admin_user):
    """Factory to create test invoices with custom data"""
    from decimal import Decimal
    from datetime import date
    from apps.invoices.models import Invoice
    
    def _create_invoice(
        invoice_number="INV-001",
        total_amount=Decimal("1000.00"),
        status=Invoice.Status.PENDING,
        **kwargs
    ):
        defaults = {
            'organization': organization,
            'uploaded_by': admin_user,
            'original_filename': f"{invoice_number}.pdf",
            'invoice_number': invoice_number,
            'invoice_date': date(2026, 3, 15),
            'vendor_name': "Test Vendor",
            'vendor_vat_number': "300000000000010",
            'currency': Invoice.Currency.SAR,
            'subtotal': Decimal("900.00"),
            'vat_amount': Decimal("135.00"),
            'total_amount': total_amount,
            'status': status,
        }
        defaults.update(kwargs)
        return Invoice.objects.create(**defaults)
    
    return _create_invoice


# ─── Markers & Test Helpers ───────────────────────────────────────────────

@pytest.fixture
def assert_response_error():
    """Helper to assert error responses"""
    def _assert(response, expected_status, expected_error_code=None):
        assert response.status_code == expected_status, \
            f"Expected {expected_status}, got {response.status_code}: {response.data}"
        
        if expected_error_code:
            assert response.data.get('code') == expected_error_code, \
                f"Expected error code {expected_error_code}, got {response.data.get('code')}"
    
    return _assert


@pytest.fixture
def assert_response_success():
    """Helper to assert successful responses"""
    def _assert(response, expected_status=200, expected_fields=None):
        assert response.status_code == expected_status, \
            f"Expected {expected_status}, got {response.status_code}: {response.data}"
        
        if expected_fields:
            for field in expected_fields:
                assert field in response.data, \
                    f"Expected field '{field}' not in response: {response.data.keys()}"
    
    return _assert


# ─── Database Cleanup & Performance ───────────────────────────────────────

@pytest.fixture(autouse=True)
def db_access_check(db):
    """Ensure all tests have proper database access"""
    pass


@pytest.fixture
def measure_query_count():
    """Measure number of database queries"""
    from django.test.utils import CaptureQueriesContext
    from django.db import connection
    
    def _measure(func):
        with CaptureQueriesContext(connection) as ctx:
            result = func()
        return result, len(ctx)
    
    return _measure


# ─── Markers Registration ──────────────────────────────────────────────────

def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line(
        "markers", "slow: marks test as slow (run with -m slow)"
    )
    config.addinivalue_line(
        "markers", "integration: marks test as integration test"
    )
    config.addinivalue_line(
        "markers", "unit: marks test as unit test"
    )
    config.addinivalue_line(
        "markers", "security: marks test as security-related"
    )
    config.addinivalue_line(
        "markers", "celery: marks test as celery task test"
    )
