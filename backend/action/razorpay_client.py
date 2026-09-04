"""Razorpay Test Mode client — order creation and webhook signature
verification. Stdlib only, no SDK, matches the smallest-integration brief.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from base64 import b64encode


class RazorpayConfigError(RuntimeError):
    pass


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RazorpayConfigError(f"{name} is not set")
    return value


def create_order(amount_paise: int, receipt: str) -> dict:
    """Create a Razorpay order. Returns Razorpay's raw order dict (has
    'id', 'amount', 'currency', etc). Raises RazorpayConfigError if the
    env vars aren't set, or urllib.error.HTTPError on a real API failure —
    let the caller decide how to surface that, do not swallow it here."""
    key_id = _require_env("RAZORPAY_KEY_ID")
    key_secret = _require_env("RAZORPAY_KEY_SECRET")
    body = json.dumps({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": receipt,
        "payment_capture": 1,
    }).encode("utf-8")
    auth = b64encode(f"{key_id}:{key_secret}".encode()).decode()
    req = urllib.request.Request(
        "https://api.razorpay.com/v1/orders",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth}",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    """Verify per Razorpay's documented scheme: HMAC-SHA256 of the raw,
    UNPARSED request body, using the webhook secret, hex-digested, compared
    to the X-Razorpay-Signature header. Must receive the exact raw bytes —
    see routes/razorpay_webhook.py for why that matters."""
    secret = _require_env("RAZORPAY_WEBHOOK_SECRET")
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")
