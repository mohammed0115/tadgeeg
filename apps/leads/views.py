from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import LeadNotFoundError, LeadsError
from .selectors import get_all_leads, get_lead_by_id, get_lead_notes, get_lead_stats
from .serializers import (
    ContactFormSerializer,
    ContactLeadDetailSerializer,
    ContactLeadListSerializer,
    LeadAssignSerializer,
    LeadNoteCreateSerializer,
    LeadNoteSerializer,
    LeadStatusUpdateSerializer,
)
from .services import (
    add_lead_note,
    assign_lead,
    delete_lead,
    mark_as_spam,
    mark_lead_read,
    submit_contact_form,
    update_lead_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_admin(user) -> bool:
    return user.is_staff or getattr(user, 'role', None) == 'admin'


class _AdminPermission(IsAuthenticated):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return _is_admin(request.user)


# ---------------------------------------------------------------------------
# Admin — Leads
# ---------------------------------------------------------------------------

class AdminLeadListView(APIView):
    """GET all leads with optional filters. Includes unread count in response header."""

    permission_classes = [_AdminPermission]

    def get(self, request):
        status_filter = request.query_params.get('status')
        source_filter = request.query_params.get('source')
        assigned_to = request.query_params.get('assigned_to')

        leads = get_all_leads(
            status=status_filter,
            source=source_filter,
            assigned_to=assigned_to if assigned_to else None,
        )
        serializer = ContactLeadListSerializer(leads, many=True)
        from .models import ContactLead
        unread_count = ContactLead.objects.filter(is_read=False).count()
        response = Response(serializer.data)
        response['X-Unread-Count'] = str(unread_count)
        return response


class AdminLeadDetailView(APIView):
    """GET detail or DELETE a single lead."""

    permission_classes = [_AdminPermission]

    def get(self, request, pk):
        lead = get_lead_by_id(pk)
        if lead is None:
            return Response({'detail': 'Lead not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(ContactLeadDetailSerializer(lead).data)

    def delete(self, request, pk):
        try:
            delete_lead(pk, user=request.user)
        except LeadNotFoundError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminLeadStatusView(APIView):
    """POST /<uuid>/status/ — update lead status."""

    permission_classes = [_AdminPermission]

    def post(self, request, pk):
        serializer = LeadStatusUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            lead = update_lead_status(pk, status=serializer.validated_data['status'], user=request.user)
        except LeadNotFoundError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(ContactLeadDetailSerializer(lead).data)


class AdminLeadAssignView(APIView):
    """POST /<uuid>/assign/ — assign lead to a user."""

    permission_classes = [_AdminPermission]

    def post(self, request, pk):
        serializer = LeadAssignSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            lead = assign_lead(pk, assignee_id=serializer.validated_data['assignee_id'], user=request.user)
        except LeadNotFoundError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except LeadsError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ContactLeadDetailSerializer(lead).data)


class AdminLeadMarkReadView(APIView):
    """POST /<uuid>/read/ — mark lead as read."""

    permission_classes = [_AdminPermission]

    def post(self, request, pk):
        try:
            lead = mark_lead_read(pk, user=request.user)
        except LeadNotFoundError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(ContactLeadDetailSerializer(lead).data)


class AdminLeadNoteListView(APIView):
    """GET notes for a lead / POST add a note."""

    permission_classes = [_AdminPermission]

    def get(self, request, pk):
        lead = get_lead_by_id(pk)
        if lead is None:
            return Response({'detail': 'Lead not found.'}, status=status.HTTP_404_NOT_FOUND)
        notes = get_lead_notes(pk)
        return Response(LeadNoteSerializer(notes, many=True).data)

    def post(self, request, pk):
        serializer = LeadNoteCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            note = add_lead_note(pk, note_text=serializer.validated_data['note'], user=request.user)
        except LeadNotFoundError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(LeadNoteSerializer(note).data, status=status.HTTP_201_CREATED)


class AdminLeadSpamView(APIView):
    """POST /<uuid>/spam/ — mark lead as spam."""

    permission_classes = [_AdminPermission]

    def post(self, request, pk):
        try:
            lead = mark_as_spam(pk, user=request.user)
        except LeadNotFoundError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(ContactLeadDetailSerializer(lead).data)


class LeadStatsView(APIView):
    """GET aggregate stats for leads."""

    permission_classes = [_AdminPermission]

    def get(self, request):
        stats = get_lead_stats()
        return Response(stats)


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

class PublicContactFormView(APIView):
    """POST /contact/ — submit a contact/inquiry form (public, no auth required)."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ContactFormSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        lead = submit_contact_form(serializer.validated_data)
        return Response(
            {
                'detail': 'Your message has been received. We will get back to you shortly.',
                'lead_id': str(lead.pk),
            },
            status=status.HTTP_201_CREATED,
        )
