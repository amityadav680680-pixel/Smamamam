# Android setup — forward SMS from YOUR phone to this server

Use this only on a phone **you own** and are allowed to monitor.
Unauthorized monitoring of someone else's messages is illegal.

## Option A — SMS Forwarder app (easiest)

1. Install an SMS Forwarder app from Play Store that supports **HTTP/Webhook**
   (examples: *SMS Forwarder*, *Tasker* + HTTP request).
2. Create a rule: **Incoming SMS → HTTP POST**.
3. URL:
   ```
   https://YOUR_PUBLIC_HOST/webhook/sms
   ```
4. Headers:
   ```
   Content-Type: application/json
   X-API-Key: <WEBHOOK_API_KEY from your .env>
   ```
5. JSON body template (field names vary by app — map accordingly):
   ```json
   {
     "sender": "{{from}}",
     "body": "{{text}}",
     "device_id": "my-android"
   }
   ```
6. Send yourself a test SMS and confirm it appears in Telegram (`/latest`).

## Option B — Tasker

1. Profile → Event → Phone → Received SMS.
2. Task → HTTP Request:
   - Method: POST
   - URL: `https://YOUR_PUBLIC_HOST/webhook/sms`
   - Headers: `Content-Type: application/json` and `X-API-Key: YOUR_KEY`
   - Body:
     ```json
     {
       "sender": "%SMSRF",
       "body": "%SMSRB",
       "device_id": "tasker-phone"
     }
     ```

## Exposing the server

The phone must reach your API over the internet:

- **Cloud VPS** (recommended): deploy with uvicorn + nginx/caddy + HTTPS
- **Tunnel for testing**: `ngrok http 8000` or Cloudflare Tunnel, then use the
  public HTTPS URL in the forwarder

Never put the webhook on the open internet without a strong `WEBHOOK_API_KEY`.

## Permissions on Android

The forwarder app needs **SMS / Receive SMS** permission. Grant it only to the
app you installed on your own device.
