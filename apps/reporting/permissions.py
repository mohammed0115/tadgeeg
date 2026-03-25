from rest_framework.permissions import BasePermission


class CanGenerateReport(BasePermission):
    """Allow access to users whose role permits report generation.

    Permitted roles
    ---------------
    * admin
    * cao  (Chief Audit Officer)
    * senior_auditor
    * compliance_officer

    Staff / superuser users are always permitted.
    """

    ALLOWED_ROLES = frozenset(
        ["admin", "cao", "senior_auditor", "compliance_officer"]
    )

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_staff or user.is_superuser:
            return True
        return getattr(user, "role", None) in self.ALLOWED_ROLES
