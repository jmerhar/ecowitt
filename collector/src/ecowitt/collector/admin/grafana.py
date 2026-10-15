"""Grafana: the dashboard and alert rules for the stored units, and pushing them over its API.

The Grafana page offers both files to copy and pushes them with a service-account token: the
dashboard through `/api/dashboards/db`, the rules as one group through the alerting provisioning
API. A push replaces the group whole -- a rule edited in Grafana is overwritten, one added to the
group there is deleted -- and leaves the rules editable in Grafana (`X-Disable-Provenance`).
Grafana's open-source edition lets a service account provision rules only with the Editor role.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx2

from ecowitt.collector.admin import lookups
from ecowitt.collector.grafana import render
from ecowitt.core.store.settings import Setting
from ecowitt.core.units import Units

#: The data source uid the rule files name, replaced by the configured one.
FILE_DATASOURCE = "weather"

SETTINGS: tuple[Setting, ...] = (
    Setting("url", "URL", format="url", help="Where Grafana answers, e.g. http://grafana:3000"),
    Setting("token", "Service-account token", secret=True, help="One with the Editor role"),
    Setting(
        "datasource",
        "Data source uid",
        default=FILE_DATASOURCE,
        help="The InfluxDB data source the rules read",
    ),
    Setting("folder", "Folder", default="Weather", help="Created if Grafana has none by this name"),
)

#: A duration as the rule files write one: a number and a unit.
DURATION = re.compile(r"(\d+)([smhd])")
SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class GrafanaError(Exception):
    """Grafana could not be reached or refused a step, in words for the page."""


def values_of(saved: Mapping[str, str]) -> dict[str, str]:
    """A connection's settings with the defaults filled in."""
    return {s.name: (saved.get(s.name) or "").strip() or s.default for s in SETTINGS}


def provisioning(units: Units, datasource: str = FILE_DATASOURCE) -> dict[str, Any]:
    """The alert rules as a provisioning file, reading `datasource`."""
    document = render.alerts(units)
    for group in document["groups"]:
        for rule in group["rules"]:
            _point_at(rule, datasource)
    return document


def rule_group(units: Units, datasource: str = FILE_DATASOURCE) -> dict[str, Any]:
    """The alert rules as the provisioning API takes a rule group.

    The API spells the file's `keepFiringFor` as `keep_firing_for` and wants the evaluation
    interval in seconds; the folder and group come from the URL it is sent to.
    """
    (group,) = provisioning(units, datasource)["groups"]
    rules = [
        {("keep_firing_for" if key == "keepFiringFor" else key): value for key, value in r.items()}
        for r in group["rules"]
    ]
    return {"title": group["name"], "interval": _seconds(group["interval"]), "rules": rules}


async def check(client: httpx2.AsyncClient, saved: Mapping[str, str]) -> str:
    """Raise GrafanaError unless the token works and the data source is InfluxDB; its name."""
    values = values_of(saved)
    await _call(client, values, "GET", "/api/user")
    uid = values["datasource"]
    source = await _call(
        client,
        values,
        "GET",
        f"/api/datasources/uid/{quote(uid, safe='')}",
        missing=f"it has no data source with uid {uid}",
    )
    if source.get("type") != "influxdb":
        raise GrafanaError(f"data source {uid} is {source.get('type')}, not InfluxDB")
    return str(source.get("name") or uid)


#: What a push can send, by the name the page's buttons give: the dashboard, the rules, or both.
PARTS: dict[str, frozenset[str]] = {
    "both": frozenset({"dashboard", "rules"}),
    "dashboard": frozenset({"dashboard"}),
    "rules": frozenset({"rules"}),
}


async def push(
    client: httpx2.AsyncClient,
    saved: Mapping[str, str],
    units: Units,
    version: str,
    parts: frozenset[str] = PARTS["both"],
) -> str:
    """Push the dashboard, the alert rules or both, rendered for `units`; what was done.

    Each part replaces only its own: the dashboard leaves the rules as they are, and the
    reverse.
    """
    values = values_of(saved)
    name = await check(client, values)
    folder = await _folder(client, values)
    done = []
    if "dashboard" in parts:
        dashboard = render.dashboard(units)
        dashboard["id"] = None
        for variable in dashboard["templating"]["list"]:
            if variable["type"] == "datasource":
                variable["current"] = {"text": name, "value": values["datasource"]}
        await _call(
            client,
            values,
            "POST",
            "/api/dashboards/db",
            json={
                "dashboard": dashboard,
                "folderUid": folder,
                "overwrite": True,
                "message": f"Pushed by Ecowitt Server {version}",
            },
        )
        done.append("the dashboard")
    if "rules" in parts:
        group = rule_group(units, values["datasource"])
        await _call(
            client,
            values,
            "PUT",
            f"/api/v1/provisioning/folder/{quote(folder, safe='')}"
            f"/rule-groups/{quote(group['title'], safe='')}",
            json=group,
            headers={"X-Disable-Provenance": "true"},
        )
        done.append(f"{len(group['rules'])} alert rules")
    return f"Pushed {' and '.join(done)} to the {values['folder']} folder."


async def _folder(client: httpx2.AsyncClient, values: Mapping[str, str]) -> str:
    """The uid of the folder named in the settings, created if Grafana has none by that name."""
    title = values["folder"]
    found = await _call(
        client, values, "GET", "/api/search", params={"type": "dash-folder", "query": title}
    )
    for item in found:
        if item.get("title") == title:
            return str(item["uid"])
    created = await _call(client, values, "POST", "/api/folders", json={"title": title})
    return str(created["uid"])


async def _call(
    client: httpx2.AsyncClient,
    values: Mapping[str, str],
    method: str,
    path: str,
    *,
    json: object = None,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    missing: str | None = None,
) -> Any:
    """One request to Grafana's API, its JSON answer, or GrafanaError saying what went wrong.

    Nothing from the answer reaches the page but Grafana's own `message`, and the token never
    does.
    """
    try:
        response = await client.request(
            method,
            values["url"].rstrip("/") + path,
            json=json,
            params=params,
            headers={
                "Authorization": f"Bearer {values['token']}",
                "Accept": "application/json",
                **(headers or {}),
            },
            timeout=lookups.TIMEOUT_SECONDS,
        )
    except httpx2.RequestError as exc:
        raise GrafanaError(f"cannot connect ({type(exc).__name__})") from exc
    status = response.status_code
    if status == 401:
        raise GrafanaError("it refused the token")
    if status == 403:
        raise GrafanaError("the token may not do this; give its service account the Editor role")
    if status == 404 and missing:
        raise GrafanaError(missing)
    if status >= 400:
        raise GrafanaError(f"it answered {status}{_reason(response)}")
    try:
        return response.json()
    except ValueError as exc:
        # A URL that reaches something other than Grafana's API, such as a login page.
        raise GrafanaError(f"its answer to {path} was not Grafana's API") from exc


def _reason(response: httpx2.Response) -> str:
    """Grafana's explanation of a refusal, when it gave one."""
    try:
        message = response.json().get("message")
    except ValueError, AttributeError:
        return ""
    return f": {str(message)[:200]}" if message else ""


def _point_at(rule: dict[str, Any], datasource: str) -> None:
    """Make a rule's queries read `datasource` instead of the files' uid."""
    for step in rule["data"]:
        if step.get("datasourceUid") == FILE_DATASOURCE:
            step["datasourceUid"] = datasource


def _seconds(duration: str) -> int:
    """A duration such as "1m" in seconds."""
    match = DURATION.fullmatch(duration)
    if not match:
        raise ValueError(f"cannot read the duration {duration!r}")
    return int(match.group(1)) * SECONDS[match.group(2)]
