"""The notifications Grafana sends, recorded as they are sent.

A second webhook beside a contact point's own delivery posts every notification here: the same
groups, at the same times, through the same quiet hours, so the record is what was sent rather
than a reconstruction of Grafana's routing. Each becomes one row of the `notification` table,
tagged with the contact point, the rule, its status and its station, and holding the message's
title and text as the webhook rendered them.

The webhook authenticates with a token the Grafana page creates. Only a hash of it is kept,
and the route skips the admin listener's host check and login, which a Grafana posting from
another container could not pass: the token is the whole gate.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from ecowitt.core.store.base import Row

#: The table the notifications are written to.
TABLE = "notification"
#: The path Grafana's webhook posts to.
PATH = "/api/notifications"
#: The largest notification accepted. Grafana's payload carries every alert in the group with
#: its labels and annotations; a house's worth is a few kilobytes.
MAX_BYTES = 256 * 1024
#: Joins a message's lines, which line protocol cannot store.
LINE_BREAK = " / "


def new_token() -> str:
    """A fresh token for the webhook to send."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """What is kept of a token: enough to check one, nothing to recover it from."""
    return hashlib.sha256(token.encode()).hexdigest()


def authorised(header: str | None, stored_hash: str | None) -> bool:
    """Whether an Authorization header carries the token whose hash is kept."""
    if not header or not stored_hash:
        return False
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    return hmac.compare_digest(token_hash(token.strip()), stored_hash)


def row(payload: Any, timestamp: int) -> Row:
    """One notification as the row recording it.

    Raises ValueError for a body that is not a Grafana webhook notification.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("alerts"), list):
        raise ValueError("not a Grafana notification: no list of alerts")
    alerts = [a for a in payload["alerts"] if isinstance(a, dict)]
    group = _labels(payload.get("groupLabels"))
    common = _labels(payload.get("commonLabels"))
    tags = {
        "receiver": _text(payload.get("receiver")),
        "status": _text(payload.get("status")),
        "rule": group.get("alertname") or common.get("alertname", ""),
    }
    if common.get("station"):
        tags["station"] = common["station"]
    fields: dict[str, Any] = {
        "alerts": float(len(alerts)),
        "title": _text(payload.get("title")),
        "message": LINE_BREAK.join(
            line.strip() for line in _text(payload.get("message")).splitlines() if line.strip()
        ),
    }
    rooms = sorted({room for a in alerts if (room := _labels(a.get("labels")).get("room"))})
    if rooms:
        fields["rooms"] = ", ".join(rooms)
    return Row(TABLE, tuple(sorted((k, v) for k, v in tags.items() if v)), timestamp, fields)


def _labels(value: Any) -> dict[str, str]:
    """A label set, with anything that is not text left out."""
    if not isinstance(value, dict):
        return {}
    return {str(k): v for k, v in value.items() if isinstance(v, str)}


def _text(value: Any) -> str:
    """A payload's text value, or nothing for anything else."""
    return value if isinstance(value, str) else ""
