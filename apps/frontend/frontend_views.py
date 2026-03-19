"""
Tadgeeg AI frontend views.
Django template-based UI for all API modules.
"""
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods


# ── helpers ──────────────────────────────────────────────────────────────────

def _ctx(request, active='dashboard', **extra):
    """Shared template context."""
    pending_count = 0
    try:
        from apps.invoices.models import Invoice
        org = getattr(request.user, 'organization', None)
        if org:
            pending_count = Invoice.objects.filter(organization=org, status='flagged').count()
    except Exception:
        pass
    return {'pending_count': pending_count, 'active': active, **extra}


def _report_types():
    return [
        {
            'type': 'invoice_audit', 'lang': 'ar',
            'label': 'تدقيق الفواتير',
            'desc': 'البنود الـ 30 + مخاطر + موردون',
            'icon': 'file-check-2',
            'bg': 'bg-blue-100 dark:bg-blue-900/30',
            'color': 'text-blue-600 dark:text-blue-400',
        },
        {
            'type': 'executive_summary', 'lang': 'ar',
            'label': 'ملخص تنفيذي',
            'desc': 'نظرة عامة للإدارة العليا',
            'icon': 'bar-chart-3',
            'bg': 'bg-violet-100 dark:bg-violet-900/30',
            'color': 'text-violet-600 dark:text-violet-400',
        },
        {
            'type': 'risk_assessment', 'lang': 'ar',
            'label': 'تقرير المخاطر',
            'desc': 'الفواتير والموردون الخطرون',
            'icon': 'shield-alert',
            'bg': 'bg-red-100 dark:bg-red-900/30',
            'color': 'text-red-600 dark:text-red-400',
        },
        {
            'type': 'vendor_analysis', 'lang': 'ar',
            'label': 'تحليل الموردين',
            'desc': 'أنماط الإنفاق ومؤشرات الخطر',
            'icon': 'building-2',
            'bg': 'bg-emerald-100 dark:bg-emerald-900/30',
            'color': 'text-emerald-600 dark:text-emerald-400',
        },
    ]


# ── Auth ──────────────────────────────────────────────────────────────────────

@ensure_csrf_cookie
def login_view(request):
    if request.user.is_authenticated:
        return redirect('frontend:dashboard')

    if request.method == 'POST':
        email    = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        user     = authenticate(request, email=email, password=password)
        if user:
            login(request, user)
            # Try to issue JWT tokens
            tokens = {}
            try:
                from rest_framework_simplejwt.tokens import RefreshToken
                refresh = RefreshToken.for_user(user)
                tokens  = {'access': str(refresh.access_token), 'refresh': str(refresh)}
            except Exception:
                pass
            return JsonResponse({'success': True, 'redirect': '/dashboard/', 'tokens': tokens})
        return JsonResponse({'success': False, 'error': 'البريد الإلكتروني أو كلمة المرور غير صحيحة'})

    return render(request, 'auth/login.html')


def logout_view(request):
    logout(request)
    return redirect('frontend:login')


# ── Dashboard ─────────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def dashboard(request):
    ctx = _ctx(request, 'dashboard', monthly_growth=12)
    return render(request, 'dashboard/index.html', ctx)


# ── Invoices ──────────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def upload(request):
    return render(request, 'invoices/upload.html', _ctx(request, 'upload'))


@login_required(login_url='/login/')
def invoices(request):
    return render(request, 'invoices/list.html', _ctx(request, 'invoices'))


@login_required(login_url='/login/')
def invoice_detail(request, pk):
    try:
        from apps.invoices.models import Invoice, InvoiceAuditEvent
        org     = getattr(request.user, 'organization', None)
        invoice = Invoice.objects.select_related('approved_by', 'duplicate_of').get(pk=pk)
        if org and invoice.organization != org:
            return redirect('frontend:invoices')
        audit_trail = InvoiceAuditEvent.objects.filter(invoice=invoice).select_related('user').order_by('-timestamp')[:40]
    except Exception:
        return redirect('frontend:invoices')

    ctx = _ctx(request, 'invoices', invoice=invoice, audit_trail=audit_trail)
    return render(request, 'invoices/detail.html', ctx)


@login_required(login_url='/login/')
def batches(request):
    return render(request, 'invoices/batches.html', _ctx(request, 'batches'))


# ── Reports ───────────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def reports(request):
    ctx = _ctx(request, 'reports', report_types=_report_types())
    return render(request, 'reports/index.html', ctx)


# ── Vendors ───────────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def vendors(request):
    return render(request, 'vendors/index.html', _ctx(request, 'vendors'))


# ── Analytics ─────────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def analytics(request):
    return render(request, 'analytics/index.html', _ctx(request, 'analytics'))


# ── Audit Cases ───────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def audit(request):
    return render(request, 'audit/index.html', _ctx(request, 'audit'))


# ── Compliance ────────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def compliance(request):
    return render(request, 'compliance/index.html', _ctx(request, 'compliance'))


# ── Documents ─────────────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def documents(request):
    return render(request, 'documents/index.html', _ctx(request, 'documents'))


# ── Typed Document Pages ──────────────────────────────────────────────────────

@login_required(login_url='/login/')
def doc_upload(request):
    doc_type = request.GET.get('type', '')
    return render(request, 'documents/upload.html', _ctx(request, 'documents', selected_type=doc_type))

@login_required(login_url='/login/')
def purchase_orders(request):
    return render(request, 'documents/purchase_orders.html', _ctx(request, 'purchase_orders'))

@login_required(login_url='/login/')
def bank_statements(request):
    return render(request, 'documents/bank_statements.html', _ctx(request, 'bank_statements'))

@login_required(login_url='/login/')
def payroll(request):
    return render(request, 'documents/payroll.html', _ctx(request, 'payroll'))

@login_required(login_url='/login/')
def expense_reports(request):
    return render(request, 'documents/expense_reports.html', _ctx(request, 'expense_reports'))

@login_required(login_url='/login/')
def vat_returns(request):
    return render(request, 'documents/vat_returns.html', _ctx(request, 'vat_returns'))

@login_required(login_url='/login/')
def fixed_assets(request):
    return render(request, 'documents/fixed_assets.html', _ctx(request, 'fixed_assets'))

@login_required(login_url='/login/')
def sales_receipts(request):
    return render(request, 'documents/sales_receipts.html', _ctx(request, 'sales_receipts'))
