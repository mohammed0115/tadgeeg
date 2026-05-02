from django.urls import path
from .views import AssistantChatView, AssistantResetView, AssistantHistoryView

urlpatterns = [
    path("chat/",    AssistantChatView.as_view(),    name="assistant-chat"),
    path("reset/",   AssistantResetView.as_view(),   name="assistant-reset"),
    path("history/", AssistantHistoryView.as_view(), name="assistant-history"),
]
