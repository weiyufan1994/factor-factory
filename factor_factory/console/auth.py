from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from http.cookies import SimpleCookie


SESSION_COOKIE = "factorforge_console_session"
SESSION_MAX_AGE_SECONDS = 12 * 60 * 60


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class InviteAuth:
    invite_password: str
    cookie_secret: str
    secure_cookie: bool = False
    disabled: bool = False

    def password_matches(self, candidate: str) -> bool:
        if self.disabled:
            return True
        return hmac.compare_digest(candidate.encode("utf-8"), self.invite_password.encode("utf-8"))

    def issue_session(self, now: int | None = None) -> str:
        issued = int(now if now is not None else time.time())
        payload = f"{issued}.{secrets.token_urlsafe(18)}"
        signature = hmac.new(self.cookie_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256)
        return f"{_b64encode(payload.encode('utf-8'))}.{_b64encode(signature.digest())}"

    def verify_session(self, token: str, now: int | None = None) -> bool:
        if self.disabled:
            return True
        try:
            encoded_payload, encoded_signature = token.split(".", 1)
            payload = _b64decode(encoded_payload).decode("utf-8")
            issued_raw, _nonce = payload.split(".", 1)
            issued = int(issued_raw)
            signature = _b64decode(encoded_signature)
        except (ValueError, TypeError, UnicodeDecodeError):
            return False
        expected = hmac.new(self.cookie_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
        current = int(now if now is not None else time.time())
        return hmac.compare_digest(signature, expected) and 0 <= current - issued <= SESSION_MAX_AGE_SECONDS

    def session_from_cookie(self, cookie_header: str | None) -> str:
        if self.disabled:
            return "auth-disabled"
        if not cookie_header:
            return ""
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception:
            return ""
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else ""

    def csrf_token(self, session_token: str) -> str:
        digest = hmac.new(
            self.cookie_secret.encode("utf-8"),
            f"csrf:{session_token}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return _b64encode(digest)

    def verify_csrf(self, session_token: str, candidate: str) -> bool:
        if self.disabled:
            return True
        return bool(candidate) and hmac.compare_digest(self.csrf_token(session_token), candidate)

    def set_cookie_header(self, token: str) -> str:
        parts = [
            f"{SESSION_COOKIE}={token}",
            "Path=/",
            f"Max-Age={SESSION_MAX_AGE_SECONDS}",
            "HttpOnly",
            "SameSite=Lax",
        ]
        if self.secure_cookie:
            parts.append("Secure")
        return "; ".join(parts)

    def clear_cookie_header(self) -> str:
        parts = [f"{SESSION_COOKIE}=", "Path=/", "Max-Age=0", "HttpOnly", "SameSite=Lax"]
        if self.secure_cookie:
            parts.append("Secure")
        return "; ".join(parts)
