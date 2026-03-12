from rest_framework import serializers
from .models import Transaction, JournalEntry

class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = "__all__"
        read_only_fields = ["id", "organization", "created_at", "updated_at", "risk_score", "risk_level"]

class JournalEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = JournalEntry
        fields = "__all__"
        read_only_fields = ["id", "organization", "posted_by", "created_at"]
