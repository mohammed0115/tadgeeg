"""Partner application endpoints.

``PartnerApplicationSubmitView`` is the only unauthenticated write path in the
product that accepts files. Its controls, in the order they run:

1. DRF throttle, scope ``partner_application`` (rate from settings, 5/day).
2. Serializer validation — every field, server-side, including the §E.6
   declaration.
3. Duplicate suppression within a configurable window.
4. Upload validation for the whole submission — extension, magic bytes, per-file
   size, total size, count — before anything is written to storage.
5. Persist inside one transaction; a bad file means no application row at all.

``PartnerApplicationAttachmentDownloadView`` is the counterpart: the ONLY way to
retrieve a submitted document, staff-only, checked per request, logged.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import FileResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.permissions import IsPlatformAdmin
from core.utils.coerce import get_client_ip

from .models import PartnerApplication, PartnerApplicationAttachment
from .serializers import PartnerApplicationSubmitSerializer
from .uploads import UploadRejected, validate_submission

logger = logging.getLogger("partners.views")

#: Form field names that carry files, mapped to their stored file_type (§E.5).
FILE_FIELDS = {
    "logo": PartnerApplicationAttachment.FileType.LOGO,
    "company_profile": PartnerApplicationAttachment.FileType.PROFILE,
    "commercial_register": PartnerApplicationAttachment.FileType.COMMERCIAL_REGISTER,
    "certificates": PartnerApplicationAttachment.FileType.CERTIFICATE,
    "other_files": PartnerApplicationAttachment.FileType.OTHER,
}


class PartnerApplicationSubmitView(APIView):
    """POST /api/v1/partners/applications/ — public, throttled, file-accepting."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "partner_application"

    def post(self, request):
        serializer = PartnerApplicationSubmitSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"detail": "Validation failed.", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = serializer.validated_data.get("email", "")

        # Duplicate suppression. Throttling limits volume per IP; this stops one
        # applicant double-submitting (impatient click, browser retry) and
        # leaving a reviewer with two identical rows to reconcile.
        window_minutes = getattr(settings, "PARTNER_APPLICATION_DEDUPE_MINUTES", 60)
        cutoff = timezone.now() - timezone.timedelta(minutes=window_minutes)
        if PartnerApplication.objects.filter(email__iexact=email, created_at__gte=cutoff).exists():
            return Response(
                {
                    "detail": (
                        "We have already received an application from this email "
                        "address recently. Our team will be in touch."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Collect every uploaded file across the five zones, then validate the
        # submission as a whole BEFORE writing anything.
        incoming = []
        for field_name, file_type in FILE_FIELDS.items():
            for uploaded in request.FILES.getlist(field_name):
                incoming.append((file_type, uploaded))

        try:
            metadata = validate_submission([f for _t, f in incoming])
        except UploadRejected as exc:
            # Nothing has been written at this point — validation happens before
            # any storage call.
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            application = serializer.save(
                submitted_ip=get_client_ip(request) or None,
                submitted_user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:300],
            )
            for (file_type, uploaded), meta in zip(incoming, metadata):
                attachment = PartnerApplicationAttachment(
                    application=application,
                    file_type=file_type,
                    original_filename=meta["original_name"],
                    stored_filename=meta["stored_name"],
                    size=meta["size"],
                    content_type=meta["content_type"],
                )
                # save(name=...) with OUR generated name — the client filename
                # never reaches the filesystem.
                attachment.file.save(meta["stored_name"], uploaded, save=False)
                attachment.save()

        logger.info(
            "Partner application received: %s (%s attachments) from %s",
            application.pk, len(incoming), get_client_ip(request),
        )
        return Response(
            {
                "detail": "Your application has been received. Thank you.",
                "reference": str(application.id),
            },
            status=status.HTTP_201_CREATED,
        )


class PartnerApplicationAttachmentDownloadView(APIView):
    """GET a submitted document. STAFF ONLY, checked per request.

    This is the only retrieval path: the files live outside MEDIA_ROOT on
    storage with no base_url, so there is no URL to guess and no web-server
    route that reaches them.
    """

    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request, pk):
        try:
            attachment = PartnerApplicationAttachment.objects.select_related(
                "application"
            ).get(pk=pk)
        except (PartnerApplicationAttachment.DoesNotExist, DjangoValidationError, ValueError):
            return Response({"detail": "Attachment not found."}, status=status.HTTP_404_NOT_FOUND)

        # §N — these carry commercial registration data; every access is logged
        # with who, what, and from where.
        logger.info(
            "[partner-doc-access] user=%s attachment=%s application=%s file=%s ip=%s",
            request.user.email, attachment.pk, attachment.application_id,
            attachment.original_filename, get_client_ip(request),
        )

        response = FileResponse(
            attachment.file.open("rb"),
            # Never the detected type: serving image/png or application/pdf
            # invites the browser to render inline. A generic octet-stream plus
            # an attachment disposition means "download", never "execute".
            content_type="application/octet-stream",
            as_attachment=True,
            filename=attachment.original_filename,
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Disposition"] = (
            f'attachment; filename="{attachment.original_filename}"'
        )
        return response
