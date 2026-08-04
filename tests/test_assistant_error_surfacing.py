"""The assistant must say why it refused, not "Something went wrong".

The subscription gate answers a chat request with a complete explanation:

    402 {"detail": "An active subscription is required to use AI features.",
         "code": "no_subscription", "redirect": "/billing/plans/"}

The chat widget read `data.answer || data.error` and dropped it, so a user
whose plan does not include AI was told something had gone wrong. Nothing had.
The product had made a decision and failed to deliver it — the same shape as
the billing menu that vanished on a database fault, and the invoice that could
not be approved because "critical failures exist" when there were none.
"""

import json
from pathlib import Path

import pytest
from django.test import Client

REPO = Path(__file__).resolve().parents[1]


def _ask(user, message="كم عدد فواتيري؟"):
    client = Client()
    client.force_login(user)
    return client.post(
        "/api/v1/assistant/chat/",
        json.dumps({"message": message}),
        content_type="application/json",
    )


# ── The refusal carries its reason ───────────────────────────────────────────

@pytest.mark.django_db
def test_an_unsubscribed_org_is_told_why_and_where_to_go(admin_user):
    response = _ask(admin_user)

    assert response.status_code == 402
    body = response.json()
    assert body["code"] == "no_subscription"
    assert body["detail"], "a refusal with no reason is indistinguishable from a fault"
    assert body["redirect"] == "/billing/plans/"


@pytest.mark.django_db
def test_the_reason_is_in_a_field_the_widget_actually_reads(admin_user):
    """THE bug. The server said `detail`; the widget looked at `answer` and
    `error`, found neither, and rendered its generic fallback."""
    body = _ask(admin_user).json()

    assert {"answer", "detail", "error"} & set(body), (
        "the response carries none of the fields the chat widget renders"
    )


def test_the_widget_reads_detail_as_well_as_answer_and_error():
    source = (REPO / "templates/layouts/dashboard_base.html").read_text(encoding="utf-8")
    handler = source.split("assistant/chat/")[1].split("finally")[0]

    assert "data.detail" in handler, "the widget still ignores `detail`"
    assert "data.answer" in handler


def test_a_named_next_page_is_offered_rather_than_dropped():
    """Telling someone their plan does not cover this and leaving them in the
    chat box is a dead end; the server already said which page to open."""
    source = (REPO / "templates/layouts/dashboard_base.html").read_text(encoding="utf-8")

    assert "data.redirect" in source
    assert 'x-if="m.link"' in source


# ── A subscribed org gets past the gate ──────────────────────────────────────

@pytest.mark.django_db
def test_a_subscribed_org_reaches_the_assistant(admin_user, monkeypatch, settings):
    """Past the gate the request must reach the model call, not another refusal.

    OpenAI is stubbed: this asserts routing and the response shape, not that a
    third party answered.
    """
    from tests.conftest import activate_trial

    activate_trial(admin_user.organization)
    settings.OPENAI_API_KEY = "sk-test-not-a-real-key"

    class _Stub:
        def __init__(self, *args, **kwargs):
            self.chat = self

        @property
        def completions(self):
            return self

        def create(self, *args, **kwargs):
            class _Message:
                content = "لديك 3 فواتير."

            class _Choice:
                message = _Message()

            class _Response:
                choices = [_Choice()]
                usage = type("U", (), {"total_tokens": 42, "prompt_tokens": 20,
                                       "completion_tokens": 22})()

            return _Response()

    monkeypatch.setattr("openai.OpenAI", _Stub)

    response = _ask(admin_user)

    assert response.status_code != 402, "the subscription gate fired for a subscribed org"
    body = response.json()
    assert "answer" in body or "detail" in body or "error" in body


@pytest.mark.django_db
def test_a_missing_api_key_is_reported_as_configuration_not_as_a_user_error(
    admin_user, settings
):
    """"Something went wrong" for an unset key sends the user to support to
    report a fault only an operator can fix."""
    from tests.conftest import activate_trial

    activate_trial(admin_user.organization)
    settings.OPENAI_API_KEY = ""

    body = _ask(admin_user).json()

    assert {"answer", "detail", "error"} & set(body)
    text = " ".join(str(v) for v in body.values()).lower()
    assert any(word in text for word in ("configur", "key", "unavailable", "مهيأ", "مفتاح")), (
        f"the message does not identify this as configuration: {body}"
    )


# ── Input validation still answers in a readable field ───────────────────────

@pytest.mark.django_db
def test_an_empty_message_is_refused_readably(admin_user):
    from tests.conftest import activate_trial

    activate_trial(admin_user.organization)
    client = Client()
    client.force_login(admin_user)

    response = client.post("/api/v1/assistant/chat/", json.dumps({"message": "  "}),
                           content_type="application/json")

    assert response.status_code == 400
    assert {"answer", "detail", "error"} & set(response.json())
