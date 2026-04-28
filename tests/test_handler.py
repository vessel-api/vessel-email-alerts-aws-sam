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


def test_ses_failure_releases_claim_and_propagates(_mock_aws):
    """If SES fails, the claim must be released so the next retry can re-send.

    Without this, every transient SES error would silently lose an email -- the
    next webhook retry would find the delivery_id already claimed and return
    200 'duplicate', and vesselapi would stop retrying.
    """
    ses, ddb = _mock_aws
    ses.send_email.side_effect = ClientError(
        {"Error": {"Code": "Throttling", "Message": "rate exceeded"}},
        "SendEmail",
    )
    body = json.dumps(load_fixture("port_arrival"))

    with pytest.raises(ClientError):
        handler.lambda_handler(_api_event(body, signature=_sign(body)), None)

    # Claim was placed, then released after the SES failure.
    ddb.put_item.assert_called_once()
    ddb.delete_item.assert_called_once()
    delete_kwargs = ddb.delete_item.call_args.kwargs
    assert delete_kwargs["Key"]["delivery_id"]["S"] == "deliv-001"


def test_retry_after_ses_failure_succeeds(_mock_aws):
    """First call fails inside SES, claim is released; second call succeeds.

    This is the end-to-end shape of the retry contract: a transient SES
    failure must NOT cause the retry to be ack'd as a duplicate.
    """
    ses, ddb = _mock_aws
    body = json.dumps(load_fixture("port_arrival"))
    event = _api_event(body, signature=_sign(body))

    # First attempt: SES throws, handler raises after releasing the claim.
    ses.send_email.side_effect = ClientError(
        {"Error": {"Code": "ServiceUnavailable", "Message": "try again"}},
        "SendEmail",
    )
    with pytest.raises(ClientError):
        handler.lambda_handler(event, None)

    assert ddb.put_item.call_count == 1
    assert ddb.delete_item.call_count == 1

    # Second attempt: SES recovers. The handler should NOT short-circuit as
    # a duplicate, because the claim was released.
    ses.send_email.side_effect = None
    resp = handler.lambda_handler(event, None)

    assert resp["statusCode"] == 200
    assert resp["body"] == "sent"
    # The retry placed a fresh claim and called SES.
    assert ddb.put_item.call_count == 2
    assert ses.send_email.call_count == 2


def test_release_failure_does_not_mask_ses_error(_mock_aws):
    """If releasing the claim also fails, the original SES error still surfaces."""
    ses, ddb = _mock_aws
    ses.send_email.side_effect = ClientError(
        {"Error": {"Code": "Throttling", "Message": "rate exceeded"}},
        "SendEmail",
    )
    ddb.delete_item.side_effect = ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}},
        "DeleteItem",
    )
    body = json.dumps(load_fixture("port_arrival"))

    with pytest.raises(ClientError) as exc_info:
        handler.lambda_handler(_api_event(body, signature=_sign(body)), None)

    # The exception that surfaces should be the SES one, not the DDB one.
    assert exc_info.value.response["Error"]["Code"] == "Throttling"
