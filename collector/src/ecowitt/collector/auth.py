"""The admin interface's optional login, and its protection against cross-site forms.

The admin listener is meant to sit on loopback behind a reverse proxy, so a login is optional.
Set from the setup page, it is checked as HTTP Basic authentication; only a salted scrypt hash
of the password is stored.

Every form submission also carries a token tied to a secret in the data directory, and must
come from a page of this server. Both are needed because of how browsers behave: they attach a
Basic login to every request automatically, so without them any website the operator visits
could post a form here -- changing stations, units or the login itself -- with the operator's
credentials.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

# scrypt cost parameters: about 16 MB and a few tens of milliseconds per check. Enough to make
# guessing a stolen hash expensive, cheap enough for a page load.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
SCHEME = "scrypt"


def hash_password(password: str) -> str:
    """A salted scrypt hash of a password, with its parameters, as one string."""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return "$".join([SCHEME, str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P), _b64(salt), _b64(digest)])


def verify_password(password: str, stored: str) -> bool:
    """Whether a password matches a stored hash. A malformed hash matches nothing."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != SCHEME:
            return False
        candidate = _scrypt(password, _unb64(salt), int(n), int(r), int(p))
        return hmac.compare_digest(candidate, _unb64(digest))
    except ValueError, TypeError:
        return False


def check_basic(header: str | None, username: str, password_hash: str) -> bool:
    """Whether an Authorization header carries these credentials.

    The username is compared in constant time as well, and the password hash is always checked,
    so a wrong username takes as long to refuse as a wrong password.
    """
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except ValueError, UnicodeDecodeError:
        return False
    given_user, sep, given_password = decoded.partition(":")
    if not sep:
        return False
    user_ok = hmac.compare_digest(given_user.encode(), username.encode())
    password_ok = verify_password(given_password, password_hash)
    return user_ok and password_ok


def load_secret(path: Path) -> bytes:
    """The data directory's signing secret, created on first use, readable by its owner only."""
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_bytes(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(value)
    return value


def csrf_token(secret: bytes) -> str:
    """The token every form on this server carries.

    The same for every page: what protects it is that another site cannot read a page from
    this one to find it.
    """
    return hmac.new(secret, b"form", hashlib.sha256).hexdigest()


def host_name(netloc: str) -> str:
    """The host name in a Host header or URL authority, without port or IPv6 brackets."""
    return (urlsplit("//" + netloc).hostname or "").lower()


def host_allowed(host: str, allowed: frozenset[str]) -> bool:
    """Whether a request's Host header names one of the host names this server answers to."""
    return "*" in allowed or host_name(host) in allowed


def form_allowed(
    token: str,
    secret: bytes,
    origin: str | None,
    referer: str | None,
    host: str,
    allowed: frozenset[str] = frozenset(),
) -> bool:
    """Whether a form submission comes from this server's own pages.

    The token must match, and the browser's Origin header -- or Referer, when a browser omits
    Origin -- must name this host, or one of the host names in `allowed`: a reverse proxy may
    hand the request on with its own address as the Host. A request carrying neither header is
    refused: every browser that could be tricked into posting cross-site sends at least one.
    """
    if not hmac.compare_digest(token.encode(), csrf_token(secret).encode()):
        return False
    claimed = origin if origin and origin != "null" else referer
    if not claimed:
        return False
    netloc = urlsplit(claimed).netloc.lower()
    return netloc == host.lower() or host_name(netloc) in (allowed - {"*"})


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
