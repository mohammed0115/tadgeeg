from apps.reporting.models import Report


def get_reports_for_org(organization, filters: dict | None = None):
    """Return a queryset of reports for *organization*, optionally filtered.

    Supported filter keys
    ---------------------
    report_type : str  — exact match on ``Report.report_type``
    status      : str  — exact match on ``Report.status``
    """
    qs = Report.objects.filter(organization=organization)

    if filters:
        if filters.get("report_type"):
            qs = qs.filter(report_type=filters["report_type"])
        if filters.get("status"):
            qs = qs.filter(status=filters["status"])

    return qs
