"""
🎯 Executive AI Report Views
واجهات برمجية وصفحات ويب لعرض التقارير التنفيذية
"""

from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
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

    # Stated rather than inherited. It is already the project default, and
    # relying on a default means a change to settings silently opens this
    # endpoint. It is also NOT the protection here: the leak below was
    # reachable by an *authenticated* caller who simply had no organisation.
    # Authentication says who is asking; the scope filter says what they may
    # read, and only the second one closes this.
    permission_classes = [IsAuthenticated]

    def get(self, request, document_type, document_id):
        """
        الحصول على التقرير التنفيذي لمستند معين
        """
        organization = getattr(request.user, "organization", None)
        if organization is None:
            # Refuse, rather than fall through to an unscoped query. See
            # _fetch_document_audit_data for what falling through used to do.
            raise PermissionDenied(
                "This report is scoped to an organization and the caller has none."
            )

        try:
            # جلب بيانات المستند من قاعدة البيانات
            audit_data_dict = self._fetch_document_audit_data(
                document_type,
                document_id,
                organization=organization,
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
        
        except (NotFound, PermissionDenied):
            # These carry their own status — 404 and 403. Swallowing them into
            # the blanket 400 below would turn "not yours" and "no scope" into
            # the same answer as a malformed request, and a cross-tenant probe
            # would be indistinguishable from a typo.
            raise
        except Exception as e:
            return Response({
                "status": "error",
                "message": str(e)
            }, status=400)

    def _fetch_document_audit_data(self, document_type, document_id, organization):
        """
        جلب بيانات التدقيق من قاعدة البيانات
        تختلف حسب نوع المستند

        ``organization`` scopes the lookup and is required. It used to default
        to None, and the filter was applied only when it was not None — the
        queryset started unfiltered and stayed that way otherwise.

        That reads as a scope filter and is the opposite of one: the single
        case it skipped is the case with no scope to enforce.

        Paraphrased rather than quoted, and deliberately. The ratchet in
        tests/test_view_query_budget.py counts manager-access markers as plain
        text across every view module, and cannot tell a quotation in a
        docstring from a query: quoting the two lines here raised its total by
        one, and so did the first attempt at this very paragraph, which named
        the marker outright. The verbatim version lives in
        tests/test_executive_report_scope.py, where it is executable code and
        is supposed to count. Any caller without an
        organisation — an authenticated user who has none, or AnonymousUser via
        the template view below — received another company's invoice number,
        totals, vendor and audit scores. Nothing routed it, so it was latent.

        Absence of an organisation is now a refusal, not a bypass. There is no
        path through this method that returns rows without a scope.
        """
        if organization is None:
            raise PermissionDenied(
                "_fetch_document_audit_data requires an organization to scope by."
            )
        from apps.invoices.models import Invoice
        from apps.documents.models import Document  # Assuming exists

        if document_type == "invoice":
            try:
                invoice = Invoice.objects.filter(organization=organization).get(
                    id=document_id
                )
                # The rule outcome lives on InvoiceValidationResult, a OneToOne
                # reachable as `invoice.validation` — not on Invoice. This block
                # read invoice.validation_score, .rules_passed, .rules_failed and
                # .failed_rules, none of which are fields of Invoice; the first
                # of them raised AttributeError. The file was shadowed by
                # apps/reports/views.py and could not be imported, so nothing
                # ever executed the line to find out.
                #
                # The relation is optional: an invoice that has not been
                # validated yet has none, and that is a real state, not an error.
                validation = getattr(invoice, "validation", None)

                return {
                    "document_type": "invoice",
                    "document_id": str(invoice.id),
                    "document_number": invoice.invoice_number,
                    "company": str(invoice.organization),
                    "total_amount": float(invoice.total_amount),
                    "currency": "SAR",
                    "compliance_score": validation.validation_score if validation else 0,
                    "risk_score": invoice.risk_score or 0,
                    "risk_level": getattr(invoice, "risk_level", None) or "low",
                    "rules_passed": validation.rules_passed if validation else 0,
                    "rules_failed": validation.rules_failed if validation else 0,
                    "failed_rules": validation.failed_rule_codes if validation else [],
                    "supplier": {
                        "name": invoice.vendor_name,
                        "vat_valid": getattr(invoice, 'vendor_vat_valid', True)
                    },
                    "zatca_compliance": 100 if invoice.has_qr_code else 0,
                    # A datetime, not its isoformat(): AuditData.audit_date is
                    # typed datetime and create_audit_data_from_dict passes this
                    # value straight through, so a string reached
                    # audit_date.isoformat() in the response builder and every
                    # request for a caller's OWN invoice answered
                    #   400 'str' object has no attribute 'isoformat'
                    # Found by driving the endpoint in a browser. The unit test
                    # here asserted only "not 403 and not 404", which a 400
                    # satisfies — so the happy path had no cover at all.
                    "audit_date": invoice.created_at
                }
            except Invoice.DoesNotExist:
                # 404, deliberately the same answer as a genuinely missing id.
                # "Exists but belongs to someone else" is itself information.
                raise NotFound(f"Invoice {document_id} not found")
        
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
