# vessel-email-alerts

Self-hosted email alerts for vesselapi notifications, on AWS Lambda + SES.

A vesselapi webhook arrives at API Gateway, the Lambda verifies the HMAC
signature, deduplicates the delivery in DynamoDB, renders the event into a
plain-text and HTML email, and SES sends it to your inbox. There are no
servers to run and no idle cost.

> **Companion blog post:** [*Self-Hosted Vessel Email Alerts in an Afternoon: AWS Lambda + SES*](https://vesselapi.com/blog/email-alerts-aws-lambda-ses)

## Architecture

```
vesselapi notification
   |  POST  (HMAC-signed JSON)
   v
API Gateway (HTTP API)
   v
Lambda
   |-- verify HMAC signature
   |-- DynamoDB: claim X-Delivery-ID (24h TTL)
   |-- render email per event type
   `-- SES SendEmail
   v
Your inbox
```

## Layout

```
src/
  handler.py         Lambda entrypoint (verify, idempotency, send)
  render.py          per-event-type renderers + dispatcher
  requirements.txt   empty -- boto3 ships with the runtime
template.yaml        SAM template (Lambda + HTTP API + DynamoDB + IAM)
samconfig.toml.example  copy to samconfig.toml and fill in
tests/               pytest unit tests + JSON fixtures
scripts/
  send-test-event.sh sign + POST a fixture against the deployed URL
```

## Prerequisites

- An AWS account with the SAM CLI installed (`brew install aws-sam-cli`).
- Python 3.12 locally (matches the Lambda runtime).
- An email address verified in SES in your target region. The default region
  in `samconfig.toml.example` is `us-east-1`.
- **A vesselapi API key on a plan that includes notifications.** Notifications
  are not part of the free tier; you need at least the *Basic* plan. See
  the table below for what each tier allows.

### vesselapi notifications by plan

| Plan    | Active notifications | Vessels per notification | Delivery channels  |
|---------|----------------------|--------------------------|--------------------|
| Free    | 0 (notifications disabled) | n/a                | n/a                |
| Basic   | up to 3              | up to 100                | webhook + WebSocket |
| Starter | up to 5              | up to 100                | webhook + WebSocket |
| Growth  | up to 10             | up to 100                | webhook + WebSocket |
| Pro     | unlimited            | up to 100                | webhook + WebSocket |

Pricing and the latest plan details: <https://vesselapi.com/pricing>. Sign up
and grab your API key at <https://dashboard.vesselapi.com/>.

For this example a single notification on the Basic plan is enough — one
subscription watching up to 100 of your vessels, fanning out to one email
inbox.

By default a new AWS account's SES is in **sandbox mode**, which means it can
only send to verified addresses. That's perfect for sending alerts to
yourself. See "Going to Production" below for sending more widely.

### Verifying an SES identity

In the AWS console -> SES -> Verified identities -> Create identity -> Email
address. Click the link AWS emails you. Use the same address for both
`ToAddress` and `FromAddress` if you're just sending to yourself.

## Deploy

```bash
cp samconfig.toml.example samconfig.toml
# edit samconfig.toml -- set WebhookSecret, ToAddress, FromAddress
# `openssl rand -hex 32` is a good default for WebhookSecret

make build
make deploy        # runs `sam deploy` using samconfig.toml

# or, the very first time, to walk through stack name / region interactively:
sam build && sam deploy --guided
```

The deploy prints a `WebhookUrl` output, e.g.

```
Outputs
-----------------------------------------
Key           WebhookUrl
Value         https://abc123xyz.execute-api.us-east-1.amazonaws.com/webhook
```

Save the URL -- you'll paste it into the vesselapi notification config next.

## Register the webhook with vesselapi

```bash
curl -X POST https://api.vesselapi.com/v1/notifications \
  -H "Authorization: Bearer $VESSELAPI_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "lambda-email-alerts",
    "imos": [9811000],
    "event_types": ["port.arrival", "port.departure", "eta.eta_changed"],
    "webhook_url": "https://abc123xyz.execute-api.us-east-1.amazonaws.com/webhook",
    "webhook_secret": "<the same secret you passed to SAM>"
  }'
```

`9811000` here is the *Ever Given* itself — handy if you want a vessel that
moves often and is easy to recognise in your inbox while you're verifying the
pipeline. Swap in whichever IMOs you actually want to watch.

The `webhook_secret` here **must** match `WebhookSecret` byte-for-byte. Drop
`event_types` to receive every event type for the watched vessels.

## Test it

### Through vesselapi (end-to-end)

```bash
curl -X POST https://api.vesselapi.com/v1/notifications/<id>/test \
  -H "Authorization: Bearer $VESSELAPI_KEY"
```

### Locally signed, against the deployed URL

```bash
WEBHOOK_URL='https://abc123xyz.execute-api.us-east-1.amazonaws.com/webhook' \
WEBHOOK_SECRET='<the secret you used at deploy>' \
  ./scripts/send-test-event.sh
```

That signs `tests/fixtures/port_arrival.json` with HMAC-SHA256 and POSTs it.
Override the payload with `FIXTURE=tests/fixtures/eta_changed.json`.

### Unit tests, no AWS required

```bash
make test
# or:
PYTHONPATH=src python -m pytest -q
```

The tests use mocked boto3 clients, so they run offline and finish in well
under a second. Use them as a starting point for your own customisations.

## Supported event types

The renderer dispatches on `event.type`:

| Event type                  | Email subject pattern                       |
|-----------------------------|---------------------------------------------|
| `port.arrival`              | `<vessel> arrived at <port>`                |
| `port.departure`            | `<vessel> departed <port>`                  |
| `eta.eta_changed`           | `<vessel> ETA shifted by <N> min`           |
| `eta.destination_changed`   | `<vessel> destination changed`              |
| `eta.draught_changed`       | `<vessel> draught <delta> m <deeper\|lighter>` |
| `position.geofence_enter`   | `<vessel> entered geofence`                 |
| `position.geofence_exit`    | `<vessel> exited geofence`                  |
| anything else               | generic `<vessel>: <event.type>` fallback   |

Add a new event type by writing one renderer in `src/render.py` and adding it
to `_RENDERERS`.

## Troubleshoot

- **`MessageRejected: Email address is not verified`**: SES is in sandbox and
  one of `FromAddress` / `ToAddress` isn't a verified identity in the region
  you deployed to. Verify both, retry.
- **`invalid signature` in CloudWatch**: the `WebhookSecret` parameter and
  the secret on the vesselapi notification don't match. They have to be
  byte-for-byte identical.
- **`missing X-Delivery-ID`**: that header is sent by vesselapi automatically;
  if you're testing by hand, supply it (the script does this for you).
- **No log group at all**: the function hasn't been invoked yet. Trigger it
  once via the script or the vesselapi `/test` endpoint and CloudWatch will
  create the group on the first invocation.

Logs live at `/aws/lambda/<stack-name>-EmailSenderFunction-<hash>`. Each log
line includes the delivery_id and event type so you can grep a specific
delivery.

## Cost

For a personal alert pipeline (tens to hundreds of events per month), pricing
in `us-east-1` as of April 2026:

| Component             | Pricing                          | Monthly @ 100 events |
|-----------------------|----------------------------------|----------------------|
| API Gateway HTTP API  | $1.00 per million requests       | ~$0.0001             |
| Lambda                | 1M req + 400k GB-s free tier     | $0                   |
| DynamoDB on-demand    | $0.625 per million writes        | ~$0.0001             |
| SES                   | $0.10 per 1,000 emails           | ~$0.01               |
| CloudWatch Logs       | ~$0.50 per GB ingested           | pennies              |

Total: somewhere between a few cents and a dollar a month. The whole stack
scales to zero when nothing's happening. AWS prices drift; check current
rates if you scale this beyond personal use.

## Going to production

The deploy above is right for "alerts to my own inbox." For wider use:

1. **Move SES out of sandbox.** SES console -> Account dashboard ->
   Request production access. AWS Support's initial response typically
   arrives within 24 hours; full approval can take longer.
2. **Use a domain identity, not an email identity.** Add the DKIM CNAMEs SES
   gives you to your DNS. Now `From: alerts@yourdomain.com` will display as
   authenticated to recipients.
3. **Wire up bounce and complaint handling.** Attach an SES Configuration
   Set to the function's `send_email` calls and route `Bounce` / `Complaint`
   events to an SNS topic (and from there into a Lambda or a dead-letter
   queue). Without this, a single typo'd `ToAddress` can land you on the
   SES suppression list silently.
4. **Move `WebhookSecret` to AWS Secrets Manager.** Replace the env var with
   a secret ARN, grant the function `secretsmanager:GetSecretValue` on that
   one ARN, and read it on cold start. Currently the secret is reachable by
   anyone with `lambda:GetFunctionConfiguration` on the function -- fine for
   personal use, not great once a team is involved.

Each is incremental; nothing here breaks as you adopt them.

## License

MIT. See [LICENSE](./LICENSE).
