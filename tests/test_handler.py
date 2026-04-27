"""Tests for the Lambda handler -- focused on signature verification.

The end-to-end flow (DynamoDB claim + SES send) is exercised against mocked
boto3 clients so the test suite stays hermetic and offline.
"""

import hashlib
import hmac
import json
import os
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

# Environment variables must exist before `handler` is imported because it
# reads them at module load.
os.environ.setdefault("WEBHOOK_SECRET", "test-secret-please-rotate")
os.environ.setdefault("TO_ADDRESS", "alerts@example.com")
os.environ.setdefault("FROM_ADDRESS", "alerts@example.com")
os.environ.setdefault("IDEMPOTENCY_TABLE", "test-idempotency")

import handler  # noqa: E402 -- imported after env setup
from conftest import load_fixture  # noqa: E402


SECRET = os.environ["WEBHOOK_SECRET"].encode()


def _sign(body: str) -> str:
    return "sha256=" + hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()


def _api_event(body: str, *, signature: str | None = None, delivery_id: str | None = "deliv-001"):
    headers = {}
    if signature is not None:
        headers["X-Signature-256"] = signature
    if delivery_id is not None:
        headers["X-Delivery-ID"] = delivery_id
    return {"body": body, "headers": headers, "isBase64Encoded": False}


@pytest.fixture(autouse=True)
def _mock_aws(monkeypatch):
    ses = MagicMock()
    ddb = MagicMock()
    ddb.put_item.return_value = {}
    monkeypatch.setattr(handler, "ses", ses)
    monkeypatch.setattr(handler, "ddb", ddb)
    return ses, ddb


def test_valid_signature_sends_email(_mock_aws):
    ses, ddb = _mock_aws
    body = json.dumps(load_fixture("port_arrival"))
    resp = handler.lambda_handler(_api_event(body, signature=_sign(body)), None)

    assert resp["statusCode"] == 200
    assert resp["body"] == "sent"
    ddb.put_item.assert_called_once()
    ses.send_email.assert_called_once()
    args = ses.send_email.call_args.kwargs
    assert args["Destination"]["ToAddresses"] == ["alerts@example.com"]
    assert "EVER GIVEN" in args["Message"]["Subject"]["Data"]


def test_invalid_signature_rejected(_mock_aws):
    ses, ddb = _mock_aws
    body = json.dumps(load_fixture("port_arrival"))
    resp = handler.lambda_handler(_api_event(body, signature="sha256=deadbeef"), None)

    assert resp["statusCode"] == 401
    ses.send_email.assert_not_called()
    ddb.put_item.assert_not_called()


def test_missing_signature_rejected(_mock_aws):
    ses, _ddb = _mock_aws
    body = json.dumps(load_fixture("port_arrival"))
    resp = handler.lambda_handler(_api_event(body, signature=None), None)
    assert resp["statusCode"] == 401
    ses.send_email.assert_not_called()


def test_signature_with_wrong_prefix_rejected(_mock_aws):
    ses, _ddb = _mock_aws
    body = json.dumps(load_fixture("port_arrival"))
    raw = _sign(body)[len("sha256="):]
    resp = handler.lambda_handler(_api_event(body, signature=f"sha1={raw}"), None)
    assert resp["statusCode"] == 401
    ses.send_email.assert_not_called()


def test_missing_delivery_id_rejected(_mock_aws):
    ses, _ddb = _mock_aws
    body = json.dumps(load_fixture("port_arrival"))
    resp = handler.lambda_handler(
        _api_event(body, signature=_sign(body), delivery_id=None), None
    )
    assert resp["statusCode"] == 400
    ses.send_email.assert_not_called()


def test_duplicate_delivery_returns_200_without_sending(_mock_aws):
    ses, ddb = _mock_aws
    ddb.put_item.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "dup"}},
        "PutItem",
    )
    body = json.dumps(load_fixture("port_arrival"))
    resp = handler.lambda_handler(_api_event(body, signature=_sign(body)), None)

    assert resp["statusCode"] == 200
    assert resp["body"] == "duplicate"
    ses.send_email.assert_not_called()


def test_malformed_body_rejected(_mock_aws):
    ses, ddb = _mock_aws
    body = "not-json-at-all"
    resp = handler.lambda_handler(_api_event(body, signature=_sign(body)), None)

    assert resp["statusCode"] == 400
    ses.send_email.assert_not_called()
    ddb.put_item.assert_not_called()


def test_body_missing_event_key_rejected(_mock_aws):
    ses, _ddb = _mock_aws
    body = json.dumps({"not_event": {}})
    resp = handler.lambda_handler(_api_event(body, signature=_sign(body)), None)
    assert resp["statusCode"] == 400
    ses.send_email.assert_not_called()


def test_base64_body_is_decoded_before_verification(_mock_aws):
    import base64

    ses, _ddb = _mock_aws
    body = json.dumps(load_fixture("eta_changed"))
    encoded = base64.b64encode(body.encode()).decode()
    event = {
        "body": encoded,
        "isBase64Encoded": True,
        "headers": {
            "X-Signature-256": _sign(body),
            "X-Delivery-ID": "deliv-b64",
        },
    }
    resp = handler.lambda_handler(event, None)
    assert resp["statusCode"] == 200
    ses.send_email.assert_called_once()
