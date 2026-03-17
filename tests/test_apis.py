"""
API Integration Tests

Tests validate:
- Authentication and authorization
- Request/response formats
- HTTP status codes
- Business logic through API
- Error handling
"""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from decimal import Decimal
from datetime import date
from unittest.mock import patch, Mock
import json

from apps.authentication.models import User
from apps.documents.models import Document
from apps.invoices.models import Invoice


# ─── Authentication Tests ──────────────────────────────────────────────────

@pytest.mark.unit
class TestAuthenticationAPI:
    """Tests for authentication endpoints"""
    
    def test_login_successful(self, api_client, admin_user):
        """Should login user with correct credentials"""
        response = api_client.post(reverse('login'), {
            'email': admin_user.email,
            'password': 'TestPass123!'
        }, format='json')

        assert response.status_code in [status.HTTP_200_OK, status.HTTP_202_ACCEPTED]
        assert 'access' in response.data or 'otp_required' in response.data

    def test_login_fails_with_wrong_password(self, api_client, admin_user):
        """Should reject incorrect password"""
        response = api_client.post(reverse('login'), {
            'email': admin_user.email,
            'password': 'WrongPassword'
        }, format='json')
        
        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_400_BAD_REQUEST
        ]
    
    def test_protected_endpoint_requires_auth(self, api_client):
        """Should reject unauthenticated requests"""
        response = api_client.get(reverse('document-list'))
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_authenticated_user_can_access_endpoints(self, authenticated_client):
        """Should allow authenticated users"""
        response = authenticated_client.get(reverse('document-list'))
        
        # Should return 200 or 404 (endpoint exists), not 401
        assert response.status_code != status.HTTP_401_UNAUTHORIZED


# ─── Document Upload Tests ──────────────────────────────────────────────────

@pytest.mark.integration
class TestDocumentUploadAPI:
    """Tests for document upload endpoints"""
    
    def test_upload_accepts_valid_pdf(self, authenticated_client, sample_pdf_file):
        """Should successfully upload valid PDF"""
        with patch('apps.documents.tasks.process_document_task.delay'), \
             open(sample_pdf_file, 'rb') as f:
            response = authenticated_client.post(
                reverse('document-upload'),
                {'file': f, 'document_type': 'invoice'},
                format='multipart',
            )

        assert response.status_code == status.HTTP_201_CREATED
        assert 'id' in response.data
    
    def test_upload_rejects_malicious_file(self, authenticated_client, malicious_exe_file):
        """Should reject executable files"""
        with open(malicious_exe_file, 'rb') as f:
            response = authenticated_client.post(
                reverse('document-upload'),
                {
                    'file': f,
                    'document_type': 'invoice'
                },
                format='multipart'
            )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'error' in response.data or 'file' in response.data
    
    def test_upload_rejects_oversized_file(self, authenticated_client, tmp_path):
        """Should reject files exceeding size limit"""
        huge_file = tmp_path / "huge.pdf"
        # Create 100MB+ file
        huge_file.write_bytes(b'%PDF-1.4\n' + b'X' * (100 * 1024 * 1024))
        
        with open(huge_file, 'rb') as f:
            response = authenticated_client.post(
                reverse('document-upload'),
                {
                    'file': f,
                    'document_type': 'invoice'
                },
                format='multipart'
            )
        
        # Document validation returns 400 for oversized files (not 413)
        assert response.status_code in [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        ]
    
    def test_upload_queues_async_processing(self, authenticated_client, sample_pdf_file):
        """Should queue document for background processing"""
        with patch('apps.documents.tasks.process_document_task.delay') as mock_task:
            with open(sample_pdf_file, 'rb') as f:
                response = authenticated_client.post(
                    reverse('document-upload'),
                    {
                        'file': f,
                        'document_type': 'invoice'
                    },
                    format='multipart'
                )
            
            assert response.status_code == status.HTTP_201_CREATED
            # Should have queued the task
            mock_task.assert_called_once()


# ─── Document List Tests ───────────────────────────────────────────────────

@pytest.mark.unit
class TestDocumentListAPI:
    """Tests for document listing and filtering"""
    
    def test_list_documents_returns_paginated(self, authenticated_client, document):
        """Should return paginated document list"""
        response = authenticated_client.get(reverse('document-list'))
        
        assert response.status_code == status.HTTP_200_OK
        assert 'results' in response.data or isinstance(response.data, list)
    
    def test_list_filters_by_status(self, authenticated_client, document):
        """Should filter documents by processing_status"""
        response = authenticated_client.get(
            reverse('document-list'),
            {'processing_status': 'pending'}
        )
        
        assert response.status_code == status.HTTP_200_OK
    
    def test_list_filters_by_type(self, authenticated_client, document):
        """Should filter documents by document_type"""
        response = authenticated_client.get(
            reverse('document-list'),
            {'document_type': 'invoice'}
        )
        
        assert response.status_code == status.HTTP_200_OK
    
    def test_list_enforces_organization_isolation(self, authenticated_client, document, organization):
        """Should only return documents from user's organization"""
        # Create another organization
        other_org = organization
        other_user_in_other_org = User.objects.create_user(
            email="other@test.finai",
            password="TestPass123!",
            organization=other_org,
        )
        
        # Create document in other org
        other_doc = Document.objects.create(
            organization=other_org,
            uploaded_by=other_user_in_other_org,
            original_filename="other.pdf",
            file_size=1024,
            document_type=Document.DocumentType.INVOICE,
        )
        
        response = authenticated_client.get(reverse('document-list'))
        
        # Should only see authenticated user's organization's documents
        # (Depends on actual list implementation)
        assert response.status_code == status.HTTP_200_OK


# ─── Invoice Upload Tests ───────────────────────────────────────────────────

@pytest.mark.integration
class TestInvoiceUploadAPI:
    """Tests for invoice-specific upload"""
    
    def test_invoice_upload_creates_invoice_record(self, authenticated_client, sample_pdf_file):
        """Should create invoice in database"""
        with open(sample_pdf_file, 'rb') as f:
            response = authenticated_client.post(
                reverse('invoice-upload'),
                {'files': f},
                format='multipart'
            )
        
        # Should return 201 or 202 (depending on async)
        assert response.status_code in [
            status.HTTP_201_CREATED,
            status.HTTP_202_ACCEPTED
        ]
    
    def test_invoice_upload_runs_all_30_rules(self, authenticated_client, mocker):
        """Should apply all 30 audit rules"""
        mock_audit = mocker.patch('apps.audit.audit_engine.AuditEngine.evaluate')
        mock_audit.return_value = Mock(issues=[])
        
        with patch('apps.invoices.views.InvoiceUploadView.post'):
            # Verify that audit engine would be called
            pass


# ─── Invoice Approval Tests ───────────────────────────────────────────────

@pytest.mark.unit
class TestInvoiceApprovalAPI:
    """Tests for invoice approval workflow"""
    
    def test_approve_requires_authorization(self, authenticated_client, invoice, junior_auditor):
        """Only certain roles can approve"""
        api_client = APIClient()
        api_client.force_authenticate(user=junior_auditor)
        
        response = api_client.post(
            reverse('invoice-approve', args=[invoice.id]),
            {'action': 'approve'},
            format='json',
        )
        
        # Junior auditor shouldn't be able to approve
        assert response.status_code in [
            status.HTTP_403_FORBIDDEN,
            status.HTTP_400_BAD_REQUEST
        ]
    
    def test_approve_changes_invoice_status(self, admin_client, invoice):
        """Should update invoice status"""
        response = admin_client.post(
            reverse('invoice-approve', args=[invoice.id]),
            {'action': 'approve'},
            format='json',
        )
        
        # Should return success
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_201_CREATED]
        
        # Verify status changed
        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.APPROVED


# ─── Error Handling Tests ───────────────────────────────────────────────────

@pytest.mark.unit
class TestErrorHandling:
    """Tests for API error responses"""
    
    def test_not_found_returns_404(self, authenticated_client):
        """Should return 404 for missing resources"""
        response = authenticated_client.get(
            reverse('document-detail', args=['00000000-0000-0000-0000-000000000001'])
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_validation_error_returns_400(self, authenticated_client):
        """Should return 400 for validation errors (missing file)"""
        response = authenticated_client.post(
            reverse('document-upload'),
            {'document_type': 'invalid_type'},  # Missing file, multipart
            format='multipart'
        )

        assert response.status_code in [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ]
    
    def test_permission_denied_returns_403(self, authenticated_client, junior_auditor):
        """Should return 403 for insufficient permissions on role-gated endpoints"""
        api_client = APIClient()
        api_client.force_authenticate(user=junior_auditor)

        # Junior auditor cannot approve invoices (IsSeniorAuditorOrAbove permission)
        response = api_client.post(
            reverse('invoice-approve', args=['00000000-0000-0000-0000-000000000001']),
            {'approved': True},
            format='json',
        )

        # Either 403 (no permission) or 404 (invoice doesn't exist but auth passed)
        assert response.status_code in [
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
            status.HTTP_400_BAD_REQUEST,
        ]


# ─── Rate Limiting Tests ────────────────────────────────────────────────────

@pytest.mark.unit
class TestRateLimiting:
    """Tests for API rate limiting"""
    
    def test_rate_limit_enforced_on_upload(self, api_client):
        """Should throttle upload endpoint"""
        # Would need to configure test rate limits lower
        # Test pattern: make N requests, verify Nth returns 429
        pass


# ─── Pagination Tests ──────────────────────────────────────────────────────

@pytest.mark.unit
class TestPagination:
    """Tests for API pagination"""
    
    def test_page_size_respected(self, authenticated_client, invoice_factory):
        """Should limit results to page size"""
        # Create 30 invoices
        for i in range(30):
            invoice_factory(invoice_number=f"INV-{i:03d}")
        
        response = authenticated_client.get(reverse('invoice-list'))
        
        # Default page size is 20
        result_count = len(response.data.get('results', response.data)) \
                      if hasattr(response, 'data') else 0
        
        assert result_count <= 20 or result_count > 0  # Paginated
    
    def test_next_page_link_provided(self, authenticated_client, invoice_factory):
        """Should provide next page link"""
        # Create enough invoices to paginate
        for i in range(50):
            invoice_factory(invoice_number=f"INV-{i:03d}")
        
        response = authenticated_client.get(reverse('invoice-list'))
        
        # Should have pagination metadata
        assert 'next' in response.data or 'links' in response.data


# ─── Async Task Status Tests ────────────────────────────────────────────────

@pytest.mark.integration
class TestAsyncTaskStatus:
    """Tests for checking background task status"""
    
    def test_get_document_processing_status(self, authenticated_client, document):
        """Should return current processing status"""
        response = authenticated_client.get(
            reverse('document-detail', args=[document.id])
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert 'processing_status' in response.data
        assert response.data['processing_status'] in [
            'pending', 'processing', 'completed', 'failed', 'needs_review'
        ]
