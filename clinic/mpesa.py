from __future__ import annotations

import base64
import json
import os
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any


def _get_env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value if value is not None else default


def _json_request(url: str, method: str, headers: dict[str, str], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}

    req = urllib.request.Request(url=url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}


@dataclass(frozen=True)
class MpesaConfig:
    env: str
    consumer_key: str
    consumer_secret: str
    shortcode: str
    passkey: str
    callback_url: str
    transaction_type: str

    @property
    def base_url(self) -> str:
        # Daraja endpoints
        return "https://api.safaricom.co.ke" if self.env == "production" else "https://sandbox.safaricom.co.ke"

    @property
    def is_configured(self) -> bool:
        return all([self.consumer_key, self.consumer_secret, self.shortcode, self.passkey, self.callback_url])


def load_mpesa_config() -> MpesaConfig:
    return MpesaConfig(
        env=_get_env("MPESA_ENV", "sandbox").strip().lower() or "sandbox",
        consumer_key=_get_env("MPESA_CONSUMER_KEY"),
        consumer_secret=_get_env("MPESA_CONSUMER_SECRET"),
        shortcode=_get_env("MPESA_SHORTCODE"),
        passkey=_get_env("MPESA_PASSKEY"),
        callback_url=_get_env("MPESA_CALLBACK_URL"),
        transaction_type=_get_env("MPESA_TRANSACTION_TYPE", "CustomerPayBillOnline"),
    )


def get_access_token(config: MpesaConfig) -> str:
    auth = base64.b64encode(f"{config.consumer_key}:{config.consumer_secret}".encode("utf-8")).decode("utf-8")
    url = f"{config.base_url}/oauth/v1/generate?grant_type=client_credentials"
    resp = _json_request(url=url, method="GET", headers={"Authorization": f"Basic {auth}"})
    token = resp.get("access_token")
    if not token:
        raise RuntimeError(f"Failed to obtain access token: {resp}")
    return token


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _password(shortcode: str, passkey: str, timestamp: str) -> str:
    return base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode("utf-8")).decode("utf-8")


def stk_push(
    *,
    config: MpesaConfig,
    token: str,
    phone_number: str,
    amount: int,
    account_reference: str,
    transaction_desc: str,
) -> dict[str, Any]:
    timestamp = _timestamp()
    payload = {
        "BusinessShortCode": config.shortcode,
        "Password": _password(config.shortcode, config.passkey, timestamp),
        "Timestamp": timestamp,
        "TransactionType": config.transaction_type or "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone_number,
        "PartyB": config.shortcode,
        "PhoneNumber": phone_number,
        "CallBackURL": config.callback_url,
        "AccountReference": account_reference,
        "TransactionDesc": transaction_desc[:13] if transaction_desc else "KEWOTA Payment",
    }
    url = f"{config.base_url}/mpesa/stkpush/v1/processrequest"
    return _json_request(url=url, method="POST", headers={"Authorization": f"Bearer {token}"}, payload=payload)
