#!/usr/bin/env bash
# Quick smoke test against a running server.
# Usage: ./scripts/test_webhook.sh [base_url] [api_key]

set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
API_KEY="${2:-change-me-to-a-long-random-secret}"

echo "== health =="
curl -sS "$BASE_URL/health" | python3 -m json.tool

echo
echo "== ingest SMS =="
curl -sS -X POST "$BASE_URL/webhook/sms" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "sender": "+919876543210",
    "body": "Your OTP is 482910. Do not share.",
    "device_id": "pixel-test"
  }' | python3 -m json.tool

echo
echo "== list SMS (admin) =="
ADMIN_KEY="${3:-change-me-admin-secret}"
curl -sS "$BASE_URL/api/sms?limit=5" \
  -H "X-Admin-Key: $ADMIN_KEY" | python3 -m json.tool

echo
echo "OK"
