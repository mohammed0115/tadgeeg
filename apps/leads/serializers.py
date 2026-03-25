from rest_framework import serializers

from .models import ContactLead, LeadNote


class LeadNoteSerializer(serializers.ModelSerializer):
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True, default=None)

    class Meta:
        model = LeadNote
        fields = ['id', 'note', 'created_by_email', 'created_at']
        read_only_fields = ['id', 'created_by_email', 'created_at']


class ContactLeadListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactLead
        fields = [
            'id',
            'full_name',
            'email',
            'company',
            'source',
            'status',
            'is_read',
            'created_at',
        ]


class ContactLeadDetailSerializer(serializers.ModelSerializer):
    notes = LeadNoteSerializer(many=True, read_only=True)
    assigned_to_email = serializers.EmailField(source='assigned_to.email', read_only=True, default=None)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True, default=None)

    class Meta:
        model = ContactLead
        fields = [
            'id',
            'full_name',
            'email',
            'phone',
            'company',
            'country',
            'subject',
            'message',
            'source',
            'status',
            'assigned_to',
            'assigned_to_email',
            'assigned_to_name',
            'is_read',
            'notes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'assigned_to_email', 'assigned_to_name', 'notes', 'created_at', 'updated_at']


class ContactFormSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=200)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default='')
    company = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    country = serializers.CharField(max_length=100, required=False, allow_blank=True, default='Saudi Arabia')
    subject = serializers.CharField(max_length=300)
    message = serializers.CharField()
    source = serializers.ChoiceField(
        choices=ContactLead.Source.choices,
        required=False,
        default=ContactLead.Source.CONTACT_FORM,
    )


class LeadStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ContactLead.Status.choices)


class LeadAssignSerializer(serializers.Serializer):
    assignee_id = serializers.UUIDField()


class LeadNoteCreateSerializer(serializers.Serializer):
    note = serializers.CharField()
