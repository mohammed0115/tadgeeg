"""HTTP API for ZATCA Phase 2 — devices, submissions, dashboard data."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import User
from apps.zatca.models import EGSDevice, InvoiceSubmission, RejectionCode
from apps.zatca.rejection_codes import seed_rejection_codes, translate_response_errors
from apps.zatca.services import onboard_egs_device, renew_egs_device, submit_invoice


PUBLISH_ROLES = {User.Role.ADMIN, User.Role.CHIEF_AUDIT_OFFICER}


def _can_manage(user) -> bool:
    return user.is_superuser or user.role in PUBLISH_ROLES


def _serialise_device(d: EGSDevice) -> dict:
    return {
        "id":             str(d.id),
        "common_name":    d.common_name,
        "serial_number":  d.serial_number,
        "branch_name":    d.branch_name,
        "environment":    d.environment,
        "status":         d.status,
        "valid_from":     d.valid_from.isoformat() if d.valid_from else None,
        "valid_until":    d.valid_until.isoformat() if d.valid_until else None,
        "csr_pem":        d.csr_pem[:80] + "…" if d.csr_pem else "",
        "has_certificate": bool(d.certificate_pem),
        "has_private_key": bool(d.private_key_encrypted),
        "has_csid_secret": bool(d.csid_secret_encrypted),
        "created_at":     d.created_at.isoformat(),
        "updated_at":     d.updated_at.isoformat(),
    }


def _serialise_submission(s: InvoiceSubmission, lang: str = "en") -> dict:
    return {
        "id":               str(s.id),
        "zatca_uuid":       str(s.zatca_uuid),
        "invoice_id":       str(s.invoice_id) if s.invoice_id else None,
        "egs_device_id":    str(s.egs_device_id) if s.egs_device_id else None,
        "submission_type":  s.submission_type,
        "status":           s.status,
        "chain_position":   s.chain_position,
        "previous_invoice_hash": s.previous_invoice_hash,
        "invoice_hash":     s.invoice_hash,
        "qr_tlv_base64":    s.qr_tlv_base64,
        "response_code":    s.response_code,
        "response_status":  s.response_status,
        "warnings":         s.response_warnings,
        "errors":           translate_response_errors(s.response_errors, lang=lang),
        "submitted_at":     s.submitted_at.isoformat() if s.submitted_at else None,
        "cleared_at":       s.cleared_at.isoformat() if s.cleared_at else None,
        "created_at":       s.created_at.isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Devices
# ─────────────────────────────────────────────────────────────────────────────

class DeviceListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"results": []})
        return Response({"results": [
            _serialise_device(d)
            for d in EGSDevice.objects.filter(organization=org).order_by("-updated_at")
        ]})

    def post(self, request):
        if not _can_manage(request.user):
            return Response({"error": "admin/CAO role required"}, status=403)
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"error": "user has no organization"}, status=400)

        for f in ("common_name", "serial_number", "organization_identifier"):
            if not request.data.get(f):
                return Response({"error": f"{f} is required"}, status=400)

        try:
            d = onboard_egs_device(
                organization=org,
                common_name=request.data["common_name"],
                serial_number=request.data["serial_number"],
                organization_identifier=request.data["organization_identifier"],
                organizational_unit=request.data.get("organizational_unit") or "Tadgeeg",
                branch_name=request.data.get("branch_name") or "",
                environment=request.data.get("environment") or "sandbox",
                location_address=request.data.get("location_address") or "",
                industry=request.data.get("industry") or "Audit Software",
                otp=request.data.get("otp") or "123456",
                is_production=bool(request.data.get("is_production", False)),
            )
        except Exception as exc:
            return Response({"error": str(exc)[:240]}, status=400)
        return Response(_serialise_device(d), status=201)


class DeviceRenewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _can_manage(request.user):
            return Response({"error": "admin/CAO role required"}, status=403)
        org = getattr(request.user, "organization", None)
        d = EGSDevice.objects.filter(pk=pk, organization=org).first()
        if not d:
            return Response({"error": "not found"}, status=404)
        d = renew_egs_device(d)
        return Response(_serialise_device(d))


# ─────────────────────────────────────────────────────────────────────────────
# Submissions
# ─────────────────────────────────────────────────────────────────────────────

class SubmissionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"results": []})
        qs = InvoiceSubmission.objects.filter(organization=org).order_by("-created_at")
        status_filter = request.GET.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        lang = "ar" if request.GET.get("lang") == "ar" else "en"
        return Response({"results": [_serialise_submission(s, lang=lang) for s in qs[:200]]})


class SubmitInvoiceView(APIView):
    """POST /api/v1/zatca/submissions/  — submit an invoice for clearance/reporting."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _can_manage(request.user):
            return Response({"error": "admin/CAO role required"}, status=403)

        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"error": "user has no organization"}, status=400)

        invoice_id = request.data.get("invoice_id")
        if not invoice_id:
            return Response({"error": "invoice_id is required"}, status=400)

        from apps.invoices.models import Invoice
        invoice = Invoice.objects.filter(pk=invoice_id, organization=org).first()
        if not invoice:
            return Response({"error": "invoice not found"}, status=404)

        mode = request.data.get("mode") or InvoiceSubmission.SubmissionType.CLEARANCE
        if mode not in dict(InvoiceSubmission.SubmissionType.choices):
            return Response({"error": f"invalid mode: {mode}"}, status=400)

        try:
            sub = submit_invoice(invoice, mode=mode)
        except Exception as exc:
            return Response({"error": str(exc)[:240]}, status=500)

        lang = "ar" if request.data.get("lang") == "ar" else "en"
        return Response(_serialise_submission(sub, lang=lang), status=201)


# ─────────────────────────────────────────────────────────────────────────────
# Compliance dashboard
# ─────────────────────────────────────────────────────────────────────────────

class ComplianceDashboardView(APIView):
    """GET /api/v1/zatca/dashboard/ — counters + readiness checklist."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"counts": {}, "readiness": []})

        # First-time call seeds the rejection-code lookup table.
        seed_rejection_codes()

        cutoff = timezone.now() - timedelta(days=30)
        subs = InvoiceSubmission.objects.filter(organization=org)
        recent = subs.filter(created_at__gte=cutoff)

        counts = {
            "total_30d":   recent.count(),
            "cleared":     recent.filter(status=InvoiceSubmission.Status.CLEARED).count(),
            "reported":    recent.filter(status=InvoiceSubmission.Status.REPORTED).count(),
            "warning":     recent.filter(status=InvoiceSubmission.Status.WARNING).count(),
            "rejected":    recent.filter(status=InvoiceSubmission.Status.REJECTED).count(),
            "pending":     recent.exclude(status__in=[
                InvoiceSubmission.Status.CLEARED,
                InvoiceSubmission.Status.REPORTED,
                InvoiceSubmission.Status.REJECTED,
                InvoiceSubmission.Status.WARNING,
            ]).count(),
        }
        if counts["total_30d"]:
            counts["clearance_rate_pct"] = round(
                (counts["cleared"] + counts["reported"] + counts["warning"])
                / counts["total_30d"] * 100, 1,
            )
        else:
            counts["clearance_rate_pct"] = None

        # Top rejection codes in the last 30 days.
        from collections import Counter
        codes_counter: Counter = Counter()
        for s in recent.filter(status=InvoiceSubmission.Status.REJECTED).only("response_errors"):
            for err in (s.response_errors or []):
                if isinstance(err, dict) and err.get("code"):
                    codes_counter[err["code"]] += 1
        top_codes = []
        if codes_counter:
            lookup = {r.code: r for r in
                      RejectionCode.objects.filter(code__in=list(codes_counter))}
            for code, n in codes_counter.most_common(10):
                rc = lookup.get(code)
                top_codes.append({
                    "code":     code,
                    "count":    n,
                    "category": rc.category if rc else "",
                    "title":    rc.title_en if rc else "",
                    "fix_hint": rc.fix_hint_en if rc else "",
                })

        # EGS device status snapshot.
        devices = list(EGSDevice.objects.filter(organization=org))
        cert_warnings = []
        for d in devices:
            if d.valid_until:
                days_left = (d.valid_until - timezone.now()).days
                if days_left < 30:
                    cert_warnings.append({
                        "device_id":   str(d.id),
                        "common_name": d.common_name,
                        "days_left":   days_left,
                        "status":      "expiring" if days_left > 0 else "expired",
                    })

        # Readiness checklist — Phase-2 onboarding gate.
        readiness = [
            {"check": "EGS device registered",
             "ok":    bool(devices),
             "hint":  "POST /api/v1/zatca/devices/ to create one"},
            {"check": "At least one device has an active certificate",
             "ok":    any(d.certificate_pem for d in devices),
             "hint":  "Onboarding flow auto-fetches the sandbox CSID"},
            {"check": "At least one cleared / reported invoice in last 30 days",
             "ok":    counts["cleared"] + counts["reported"] > 0,
             "hint":  "Submit an invoice via POST /api/v1/zatca/submissions/"},
            {"check": "No certificates expiring within 30 days",
             "ok":    not cert_warnings,
             "hint":  "Trigger renew via POST /api/v1/zatca/devices/<id>/renew/"},
            {"check": "Rejection codes lookup seeded",
             "ok":    RejectionCode.objects.exists(),
             "hint":  "Auto-seeded on first dashboard load"},
        ]

        return Response({
            "counts":         counts,
            "top_rejections": top_codes,
            "cert_warnings":  cert_warnings,
            "readiness":      readiness,
            "device_count":   len(devices),
        })
