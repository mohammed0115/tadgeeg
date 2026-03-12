from django.urls import re_path

from core.websocket import AlertConsumer


websocket_urlpatterns = [
    re_path(r"^ws/alerts/$", AlertConsumer.as_asgi()),
]
