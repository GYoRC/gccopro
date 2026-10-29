"""Web Push sending: payload encryption (RFC 8291), VAPID auth (RFC 8292), delivery.

Uses the pure-Python `ecdsa` package for P-256 and :mod:`gccpro.aesgcm` for
AES-GCM, because `cryptography` cannot be installed on the NAS.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import certifi
from ecdsa import ECDH, NIST256p, SigningKey, VerifyingKey
from ecdsa.util import sigencode_string
from flask import current_app

from . import aesgcm
from .db import get_db

log = logging.getLogger(__name__)

#: Record size advertised in the aes128gcm header; payloads are always smaller.
RECORD_SIZE = 4096
#: How long push services keep an undelivered message, in seconds.
TTL = 12 * 3600
#: Host suffixes of the browser push services. A subscription endpoint is a URL the
#: server will POST to, so anything else (e.g. a LAN address) is refused.
PUSH_HOST_SUFFIXES = (
    ".googleapis.com",             # Chrome / Android (FCM)
    ".push.services.mozilla.com",  # Firefox
    ".notify.windows.com",         # Edge / Windows
    ".push.apple.com",             # Safari / iOS
)


def b64url_encode(data: bytes) -> str:
    """Base64url without padding, as used throughout Web Push."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    """Decode base64url, tolerating missing padding."""
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def endpoint_allowed(endpoint: str) -> bool:
    """Return True if ``endpoint`` is an https URL on a known push service host."""
    try:
        parts = urlsplit(endpoint)
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    return parts.scheme == "https" and host.endswith(PUSH_HOST_SUFFIXES)


def keys_valid(p256dh: str, auth: str) -> bool:
    """Return True if the browser keys can be used: a P-256 point and a 16-byte secret."""
    try:
        VerifyingKey.from_string(b64url_decode(p256dh), curve=NIST256p)
        return len(b64url_decode(auth)) == 16
    except Exception:  # bad base64, wrong length or a point not on the curve
        return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: a push service never needs one, and following could reach internal hosts."""

    def redirect_request(self, *args, **kwargs):
        return None


def _hmac_sha256(key: bytes, data: bytes) -> bytes:
    """HMAC-SHA-256, the building block of HKDF in RFC 8291."""
    return hmac.new(key, data, hashlib.sha256).digest()


# --- VAPID keys -----------------------------------------------------------------

def generate_vapid_private_key() -> str:
    """Return a new P-256 private key as base64url of the raw 32-byte scalar."""
    return b64url_encode(SigningKey.generate(curve=NIST256p).to_string())


def _signing_key(private_b64: str) -> SigningKey:
    """Load a VAPID private key stored as raw base64url."""
    return SigningKey.from_string(b64url_decode(private_b64), curve=NIST256p)


def vapid_public_key(private_b64: str) -> str:
    """Return the public key browsers need (``applicationServerKey``), base64url."""
    return b64url_encode(_signing_key(private_b64).get_verifying_key().to_string("uncompressed"))


def vapid_authorization(endpoint: str, private_b64: str, subject: str, now: float | None = None) -> str:
    """Build the ``Authorization: vapid t=..., k=...`` header value for ``endpoint``."""
    url = urlsplit(endpoint)
    claims = {
        "aud": f"{url.scheme}://{url.netloc}",
        "exp": int(now if now is not None else time.time()) + TTL,
        "sub": subject,
    }
    header = {"typ": "JWT", "alg": "ES256"}
    signing_input = (
        b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + b64url_encode(json.dumps(claims, separators=(",", ":")).encode())
    )
    signature = _signing_key(private_b64).sign(
        signing_input.encode("ascii"), hashfunc=hashlib.sha256, sigencode=sigencode_string
    )
    token = signing_input + "." + b64url_encode(signature)
    return f"vapid t={token}, k={vapid_public_key(private_b64)}"


# --- Payload encryption (RFC 8291) ------------------------------------------------

def encrypt(
    payload: bytes,
    ua_public: bytes,
    auth_secret: bytes,
    *,
    as_private: SigningKey | None = None,
    salt: bytes | None = None,
) -> bytes:
    """Encrypt ``payload`` for one browser subscription, in ``aes128gcm`` format.

    Args:
        payload: The message bytes (well under 4 KB).
        ua_public: The subscription's ``p256dh`` key (65-byte uncompressed point).
        auth_secret: The subscription's 16-byte ``auth`` secret.
        as_private: Ephemeral server key; random unless given (tests use RFC values).
        salt: 16-byte salt; random unless given.

    Returns:
        The full request body: header (salt, record size, key id) then ciphertext.
    """
    as_private = as_private or SigningKey.generate(curve=NIST256p)
    salt = salt or os.urandom(16)
    as_public = as_private.get_verifying_key().to_string("uncompressed")

    ecdh = ECDH(curve=NIST256p)
    ecdh.load_private_key(as_private)
    ecdh.load_received_public_key_bytes(ua_public)
    shared = ecdh.generate_sharedsecret_bytes()

    # HKDF steps, written out as in RFC 8291 section 3.4.
    prk_key = _hmac_sha256(auth_secret, shared)
    key_info = b"WebPush: info\x00" + ua_public + as_public
    ikm = _hmac_sha256(prk_key, key_info + b"\x01")
    prk = _hmac_sha256(salt, ikm)
    cek = _hmac_sha256(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac_sha256(prk, b"Content-Encoding: nonce\x00\x01")[:12]

    # Single record: payload followed by the 0x02 "last record" delimiter.
    ciphertext = aesgcm.encrypt(cek, nonce, payload + b"\x02")
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + ciphertext


# --- Delivery ---------------------------------------------------------------------

def deliver(subscription: dict, message: dict) -> int:
    """POST one encrypted message to a push service.

    Args:
        subscription: Mapping with ``endpoint``, ``p256dh`` and ``auth``.
        message: JSON-serialisable dict read by ``static/sw.js`` (title, body, url).

    Returns:
        The HTTP status code (201 on success; 404/410 mean the subscription is gone).
    """
    cfg = current_app.config
    if not endpoint_allowed(subscription["endpoint"]):
        raise ValueError("push endpoint is not a known push service")
    body = encrypt(
        json.dumps(message, ensure_ascii=False).encode("utf-8"),
        b64url_decode(subscription["p256dh"]),
        b64url_decode(subscription["auth"]),
    )
    request = urllib.request.Request(
        subscription["endpoint"],
        data=body,
        method="POST",
        headers={
            "Authorization": vapid_authorization(
                subscription["endpoint"], cfg["VAPID_PRIVATE_KEY"], cfg["VAPID_SUBJECT"]
            ),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(TTL),
            "Urgency": "normal",
        },
    )
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=context))
        with opener.open(request, timeout=15) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def send_to_resident(resident_id: int, title: str, body: str, url: str = "/") -> int:
    """Send a notification to every device a resident subscribed.

    Subscriptions the push service reports as expired (404/410) are deleted.
    Any error on one subscription (network, bad key, refused endpoint) is logged and
    counts as a failure; the remaining subscriptions are still tried.

    Returns:
        The number of devices that accepted the message.
    """
    db = get_db()
    subs = db.execute(
        "SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE resident_id = ?",
        (resident_id,),
    ).fetchall()
    message = {"title": title, "body": body, "url": url}
    delivered = 0
    for sub in subs:
        try:
            status = deliver(dict(sub), message)
        except Exception as exc:  # one broken subscription must not stop the others
            log.warning("push to subscription %s failed: %s", sub["id"], exc)
            continue
        if status in (404, 410):
            with db:
                db.execute("DELETE FROM push_subscriptions WHERE id = ?", (sub["id"],))
        elif 200 <= status < 300:
            delivered += 1
        else:
            log.warning("push service answered %s for subscription %s", status, sub["id"])
    return delivered
