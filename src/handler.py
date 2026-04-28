"""Lambda entrypoint for vesselapi webhook -> SES email alerts.

Pipeline:
    1. Verify the HMAC-SHA256 signature on the raw request body.
    2. Claim the X-Delivery-ID in DynamoDB (conditional put with TTL).
       Duplicates short-circuit with HTTP 200 so the sender stops retrying.
    3. Render the event into subject + HTML + text bodies.
    4. SendEmail via SES. If SES fails, release the claim so vesselapi's
       next retry can try again instead of being ack'd as a duplicate.

Configuration is via environment variables, populated by the SAM template.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from render import render_email

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Module-scope clients are reused across warm invocations -- one TLS handshake
# per container, not one per request.
ses = boto3.client("ses")
ddb = boto3.client("dynamodb")

WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"].encode()
TO_ADDRESS = os.environ["TO_ADDRESS"]
FROM_ADDRESS = os.environ["FROM_ADDRESS"]
IDEMPOTENCY_TABLE = os.environ["IDEMPOTENCY_TABLE"]

IDEMPOTENCY_TTL_HOURS = 24


def lambda_handler(event, _context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    raw = event.get("body") or ""
    body: bytes = (
        base64.b64decode(raw) if event.get("isBase64Encoded") else raw.encode("utf-8")
    )

    delivery_id = headers.get("x-delivery-id", "")

    if not _verify_signature(body, headers.get("x-signature-256", "")):
        logger.warning(
            "rejected webhook: invalid signature (delivery_id=%s)",
            delivery_id or "<missing>",
        )
        return _resp(401, "invalid signature")

    if not delivery_id:
        logger.warning("rejected webhook: missing X-Delivery-ID header")
        return _resp(400, "missing X-Delivery-ID")

    try:
        payload = json.loads(body)
        evt = payload["event"]
        event_type = evt["type"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning(
            "rejected webhook: malformed body (delivery_id=%s, error=%s)",
            delivery_id,
            exc,
        )
        return _resp(400, "malformed body")

    if not _claim_delivery(delivery_id):
        logger.info(
            "duplicate delivery (delivery_id=%s, event_type=%s)",
            delivery_id,
            event_type,
        )
        # Already processed -- ack so vesselapi stops retrying.
        return _resp(200, "duplicate")

    subject, html, text = render_email(evt)

    try:
        ses.send_email(
            Source=FROM_ADDRESS,
            Destination={"ToAddresses": [TO_ADDRESS]},
            Message={
                "Subject": {"Data": subject},
                "Body": {
                    "Html": {"Data": html},
                    "Text": {"Data": text},
                },
            },
        )
    except Exception:
        # Release the claim so the next retry can try again. Without this,
        # any SES failure would silently lose the email -- the retry would
        # find the delivery_id already claimed and ack it as a duplicate.
        _release_delivery(delivery_id)
        raise

    logger.info(
        "sent email (delivery_id=%s, event_type=%s)", delivery_id, event_type
    )
    return _resp(200, "sent")


def _verify_signature(body: bytes, sig_header: str) -> bool:
    """Constant-time HMAC-SHA256 verification of the raw request body."""
    if not sig_header.startswith("sha256="):
        return False
    expected = sig_header[len("sha256="):]
    mac = hmac.new(WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, expected)


def _claim_delivery(delivery_id: str) -> bool:
    """Reserve a delivery_id in DynamoDB; return False if it already existed."""
    ttl = int(
        (datetime.now(timezone.utc) + timedelta(hours=IDEMPOTENCY_TTL_HOURS)).timestamp()
    )
    try:
        ddb.put_item(
            TableName=IDEMPOTENCY_TABLE,
            Item={
                "delivery_id": {"S": delivery_id},
                "expires_at": {"N": str(ttl)},
            },
            ConditionExpression="attribute_not_exists(delivery_id)",
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def _release_delivery(delivery_id: str) -> None:
    """Best-effort delete of a claim row so a retry can re-attempt."""
    try:
        ddb.delete_item(
            TableName=IDEMPOTENCY_TABLE,
            Key={"delivery_id": {"S": delivery_id}},
        )
    except ClientError as e:
        # If we can't release it, the retry will be ack'd as duplicate. Log
        # loudly so it's visible in CloudWatch but don't mask the SES error
        # this is unwinding from.
        logger.error(
            "failed to release claim after send error (delivery_id=%s): %s",
            delivery_id,
            e,
        )


def _resp(status: int, body: str):
    return {"statusCode": status, "body": body}
