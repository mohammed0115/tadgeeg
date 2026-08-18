"""
🎯 Executive AI Report Views
واجهات برمجية وصفحات ويب لعرض التقارير التنفيذية
"""

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import render
from django.http import JsonResponse
from django.utils.translation import get_language
from .services.executive_ai_report_service import (
    ExecutiveAIReportGenerator,
    create_audit_data_from_dict
)


@api_view(['POST'])
def generate_executive_report_api(request):
    """
    API Endpoint: Generate Executive AI Report
    
    POST /api/v1/reports/executive-report/
    
    Payload:
    {
        "document_type": "purchase_order",
        "document_number": "PO-2026-001",
        ...audit data...
    }
    """
    try:
        data = request.data
        
        # تحويل البيانات
        audit_data = create_audit_data_from_dict(data)
        
        # توليد التقرير
        generator = ExecutiveAIReportGenerator()
        language = getattr(request, 'LANGUAGE_CODE', None) or get_language() or 'ar'
        report = generator.generate_report(audit_data, language=language)
        
        return Response({
            "status": "success",
            "report": report,
            "document": {
                "type": audit_data.document_type.value,
                "number": audit_data.document_number,
                "amount": audit_data.total_amount,
                "currency": audit_data.currency
            }
        })
    
    except Exception as e:
        return Response({
            "status": "error",
            "message": str(e)
        }, status=400)


class ExecutiveReportDetailView(APIView):
    """
    GET /api/v1/reports/{document_type}/{document_id}/executive-report/
    
    يحضر بيانات المستند + يولد التقرير التنفيذي تلقائياً
    """
    
    def get(self, request, document_type, document_id):
        """
        الحصول على التقرير التنفيذي لمستند معين
        """
        try:
            # جلب بيانات المستند من قاعدة البيانات
            audit_data_dict = self._fetch_document_audit_data(
                document_type,
                document_id,
                organization=getattr(request.user, "organization", None),
            )
            
            # تحويل البيانات
            audit_data = create_audit_data_from_dict(audit_data_dict)
            
            # توليد التقرير
            generator = ExecutiveAIReportGenerator()
            language = getattr(request, 'LANGUAGE_CODE', None) or get_language() or 'ar'
            report = generator.generate_report(audit_data, language=language)
            
            return Response({
                "status": "success",
                "report": report,
                "metadata": {
                    "generated_at": audit_data.audit_date.isoformat(),
                    "auditor": audit_data.auditor_name,
                    "compliance_score": audit_data.compliance_score,
                    "risk_score": audit_data.risk_score,
                    "risk_level": audit_data.risk_level.value
                }
            })
        
        except Exception as e:
            return Response({
                "status": "error",
                "message": str(e)
            }, status=400)
    
    def _fetch_document_audit_data(self, document_type, document_id, organization=None):
        """
        جلب بيانات التدقيق من قاعدة البيانات
        تختلف حسب نوع المستند

        ``organization`` scopes the lookup. It is not optional in spirit: without
        it this method returned another company's invoice number, totals and
        audit scores to any authenticated caller. The view is not routed today,
        so that was latent rather than exploitable — but the filter belongs here,
        not in whichever URLconf eventually wires it up.
        """
        from apps.invoices.models import Invoice
        from apps.documents.models import Document  # Assuming exists

        if document_type == "invoice":
            try:
                scoped = Invoice.objects.all()
                if organization is not None:
                    scoped = scoped.filter(organization=organization)
                invoice = scoped.get(id=document_id)
                return {
                    "document_type": "invoice",
                    "document_id": str(invoice.id),
                    "document_number": invoice.invoice_number,
                    "company": str(invoice.organization),
                    "total_amount": float(invoice.total_amount),
                    "currency": "SAR",
                    "compliance_score": invoice.validation_score or 0,
                    "risk_score": invoice.risk_score or 0,
                    "risk_level": invoice.risk_level or "low",
                    "rules_passed": invoice.rules_passed or 0,
                    "rules_failed": invoice.rules_failed or 0,
                    "failed_rules": invoice.failed_rules or [],
                    "supplier": {
                        "name": invoice.vendor_name,
                        "vat_valid": getattr(invoice, 'vendor_vat_valid', True)
                    },
                    "zatca_compliance": 100 if invoice.has_qr_code else 0,
                    "audit_date": invoice.created_at.isoformat() if invoice.created_at else None
                }
            except Invoice.DoesNotExist:
                raise ValueError(f"Invoice {document_id} not found")
        
        elif document_type == "purchase_order":
            # Similar logic for PO
            # To be implemented based on actual PO model
            raise NotImplementedError("PO audit data not yet implemented")
        
        elif document_type == "bank_statement":
            raise NotImplementedError("Bank statement audit data not yet implemented")
        
        else:
            raise ValueError(f"Unknown document type: {document_type}")


def executive_report_view(request, document_type, document_id):
    """
    Django Template View: Render Executive Report as HTML
    
    GET /reports/{document_type}/{document_id}/executive-report/
    """
    try:
        # جلب البيانات والتقرير
        api_view = ExecutiveReportDetailView()
        response = api_view.get(request, document_type, document_id)
        
        if response.status_code == 200:
            data = response.data
            return render(request, 'reports/executive_report.html', {
                'report': data['report'],
                'metadata': data.get('metadata', {}),
                'document_type': document_type,
                'document_id': document_id
            })
        else:
            return render(request, 'reports/executive_report_error.html', {
                'error': response.data.get('message')
            }, status=400)
    
    except Exception as e:
        return render(request, 'reports/executive_report_error.html', {
            'error': str(e)
        }, status=400)
