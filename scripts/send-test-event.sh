#!/usr/bin/env bash
# Send a signed test webhook to your deployed Lambda URL.
#
# Required env vars:
#   WEBHOOK_URL    -- the value SAM printed as `WebhookUrl` after deploy
#   WEBHOOK_SECRET -- the same secret you passed to `sam deploy`
#
# Optional:
#   FIXTURE        -- path to a JSON fixture (default: tests/fixtures/port_arrival.json)
#
# Usage:
#   WEBHOOK_URL=https://abc.execute-api.us-east-1.amazonaws.com/webhook \
#   WEBHOOK_SECRET=your-secret \
#     ./scripts/send-test-event.sh
#
# Or with a different event:
#   FIXTURE=tests/fixtures/eta_changed.json ./scripts/send-test-event.sh

set -euo pipefail

: "${WEBHOOK_URL:?WEBHOOK_URL is required}"
: "${WEBHOOK_SECRET:?WEBHOOK_SECRET is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FIXTURE="${FIXTURE:-${REPO_ROOT}/tests/fixtures/port_arrival.json}"

if [[ ! -f "${FIXTURE}" ]]; then
  echo "fixture not found: ${FIXTURE}" >&2
  exit 1
fi

BODY="$(cat "${FIXTURE}")"
SIG="sha256=$(printf '%s' "${BODY}" | openssl dgst -sha256 -hmac "${WEBHOOK_SECRET}" | awk '{print $2}')"
DELIVERY_ID="test-$(date -u +%Y%m%dT%H%M%SZ)-$$"

echo "POST ${WEBHOOK_URL}"
echo "  fixture:     ${FIXTURE}"
echo "  delivery-id: ${DELIVERY_ID}"

curl -sS -X POST "${WEBHOOK_URL}" \
  -H "Content-Type: application/json" \
  -H "X-Signature-256: ${SIG}" \
  -H "X-Delivery-ID: ${DELIVERY_ID}" \
  --data-binary "${BODY}" \
  -w '\nHTTP %{http_code}\n'
