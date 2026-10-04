"""Client for the PGH2O Customer Advantage Portal (myaccount.pgh2o.com).

The portal has no public API. This client copies what the web page does:

1. GET /            -> hidden form field "Token"
2. RequestBroker    CustomerAdvantage_Login        -> new token
3. POST /AccountSummary (form: Token)              -> page with a new token
4. RequestBroker    CustomerAdvantage_CampaignManager -> new token
5. POST /Track (form: Token)                       -> page with token + account number
6. RequestBroker    CustomerAdvantage_GetHourlyGraph -> two years of hourly gallons

A page token can be used for several API calls on that page. Each API
response returns a new token, which the next page navigation uses.

Run this file directly to test the login outside Home Assistant:

    PGH2O_USER=... PGH2O_PASS=... python3 api.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
import json
import re
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

BASE_URL = "https://myaccount.pgh2o.com"
BROKER_URL = f"{BASE_URL}/api/WebApi/RequestBroker"
LOCAL_TZ = ZoneInfo("America/New_York")
# The hourly labels have 24 hours on every day, also on DST change days.
# Thus they use a fixed offset. The series starts in summer time, so UTC-4
# is the most likely offset. Test: run a tap at a known time and find the
# label hour that shows the use.
LABEL_TZ = timezone(timedelta(hours=-4))
TAIL_CHECK = timedelta(hours=72)
# The earlier meter reported only in 1000-gallon steps. Those hours make
# 1000-gallon spikes in the Energy dashboard, so they are not imported.
COARSE_STEP = 1000.0

_TOKEN_RE = re.compile(r'name="Token"[^>]*value="([0-9a-fA-F]+)"')
_ACCOUNT_RE = re.compile(r'id="accountSelector"[^>]*>\s*<option[^>]*value="(\d+)"')
_ACCOUNT_JS_RE = re.compile(r'AccountNumber\s*:\s*"(\d+)"')


class PGH2OError(Exception):
    """General portal error."""


class InvalidAuth(PGH2OError):
    """The portal refused the credentials."""


@dataclass
class HourlyPoint:
    """One hour, as the portal labels it (local wall-clock time)."""

    local: datetime  # naive, portal label clock (LABEL_TZ)
    normal: float
    leak: float
    unavailable: bool


@dataclass
class HourlyData:
    """Result of one fetch."""

    account: str
    last_updated: datetime  # aware
    points: list[HourlyPoint]


def parse_token(html: str) -> str:
    """Get the hidden form token from a portal page."""
    match = _TOKEN_RE.search(html)
    if not match:
        raise PGH2OError("No token in page")
    return match.group(1)


def parse_account(html: str) -> str:
    """Get the selected account number from the Track page."""
    match = _ACCOUNT_RE.search(html) or _ACCOUNT_JS_RE.search(html)
    if not match:
        raise PGH2OError("No account number in page")
    return match.group(1)


def parse_hourly(account: str, result: dict[str, Any]) -> HourlyData:
    """Convert a GetHourlyGraph result into HourlyData."""
    labels = result["ComplexLabels"]
    series = {ds["label"]: ds["data"] for ds in result["ComplexSlidingGraphDataSets"]}
    normal = series.get("Normal Use", [])
    leak = series.get("Possible Leak", [])
    unavailable = series.get("Data Unavailable", [])

    def num(values: list, i: int) -> float:
        try:
            return float(values[i] or 0)
        except (IndexError, ValueError):
            return 0.0

    points = [
        HourlyPoint(
            local=datetime.fromisoformat(f"{day}T{time}"),
            normal=num(normal, i),
            leak=num(leak, i),
            unavailable=num(unavailable, i) > 0,
        )
        for i, (day, time) in enumerate(labels)
    ]
    return HourlyData(
        account=account,
        last_updated=datetime.fromisoformat(result["LastUpdated"]),
        points=points,
    )


def hourly_points(data: HourlyData) -> list[tuple[datetime, float]]:
    """Return (UTC hour start, gallons) for hours that have final data.

    Hours at or after LastUpdated are future placeholders. Near the end of
    the data, the portal marks hours "Data Unavailable" and fills them in
    later, so the result stops at the first such hour in the last 72 hours.
    The result starts at the first reading with fine resolution.
    """
    hours = [
        (p.local.replace(tzinfo=LABEL_TZ).astimezone(UTC), p.normal + p.leak, p.unavailable)
        for p in data.points
    ]
    cut = data.last_updated.astimezone(UTC)
    hours = [h for h in hours if h[0] < cut]
    gaps = [h[0] for h in hours if h[2] and h[0] >= cut - TAIL_CHECK]
    if gaps:
        cut = min(gaps)
    first_fine = next(
        (start for start, gal, _ in hours if gal > 0 and gal % COARSE_STEP), None
    )
    if first_fine is None:
        return []
    return sorted(
        (start, gal) for start, gal, _ in hours if first_fine <= start < cut
    )


class PGH2OClient:
    """Log in and get hourly usage."""

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str) -> None:
        self._session = session
        self._username = username
        self._password = password

    def _headers(self, referer: str) -> dict[str, str]:
        return {
            "Origin": BASE_URL,
            "Referer": referer,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

    async def _broker(
        self, action: str, view: str, token: str, referer: str, **fields: Any
    ) -> tuple[dict[str, Any], str]:
        body = {"Actions": action, **fields, "Token": token, "ViewName": view, "SitePrefix": ""}
        async with self._session.post(
            BROKER_URL,
            json={"Request": json.dumps(body)},
            headers=self._headers(referer),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
        if not data.get("Authorized") or not data.get("Validated"):
            raise InvalidAuth(f"{action}: not authorized")
        result = data.get(action) or {}
        if not result.get("Success"):
            msg = result.get("ErrorMessage") or result.get("StatusMessage") or "failed"
            raise PGH2OError(f"{action}: {msg}")
        return result, data.get("Token") or token

    async def _page(self, path: str, token: str, referer: str) -> str:
        async with self._session.post(
            f"{BASE_URL}{path}",
            data={"Token": token, "SitePrefix": ""},
            headers={"Origin": BASE_URL, "Referer": referer},
        ) as resp:
            resp.raise_for_status()
            return await resp.text()

    async def async_fetch_hourly(self) -> HourlyData:
        """Log in and get the hourly graph data."""
        self._session.cookie_jar.clear()

        async with self._session.get(f"{BASE_URL}/") as resp:
            resp.raise_for_status()
            token = parse_token(await resp.text())

        try:
            login, token = await self._broker(
                "CustomerAdvantage_Login",
                "Login",
                token,
                f"{BASE_URL}/",
                UserName=self._username,
                Password=self._password,
                Language="",
                Site={"RedirectUrl": ""},
            )
        except PGH2OError as err:
            raise InvalidAuth(str(err)) from err
        for flag in ("ProfileDisabled", "Restricted", "IPAddressBlocked",
                     "PasswordChangeRequired", "EmailVerificationRequired"):
            if login.get(flag):
                raise InvalidAuth(f"Login blocked: {flag}")
        if login.get("MFAToken") or login.get("VerificationChannel"):
            raise InvalidAuth("Login needs multi-factor verification")

        html = await self._page("/AccountSummary", token, f"{BASE_URL}/")
        token = parse_token(html)
        _, token = await self._broker(
            "CustomerAdvantage_CampaignManager", "AccountSummary", token,
            f"{BASE_URL}/AccountSummary", Event="",
        )

        html = await self._page("/Track", token, f"{BASE_URL}/AccountSummary")
        token = parse_token(html)
        account = parse_account(html)

        result, _ = await self._broker(
            "CustomerAdvantage_GetHourlyGraph", "Track", token, f"{BASE_URL}/Track",
            AccountNumber=account, Template="RealTimeChart",
            StartDate="", EndDate="", GroupData=True,
        )
        return parse_hourly(account, result)


if __name__ == "__main__":
    import asyncio
    import os

    async def _main() -> None:
        async with aiohttp.ClientSession() as session:
            client = PGH2OClient(session, os.environ["PGH2O_USER"], os.environ["PGH2O_PASS"])
            data = await client.async_fetch_hourly()
            pts = hourly_points(data)
            print(f"Account {data.account}, last updated {data.last_updated}")
            print(f"{len(pts)} final hours, {pts[0][0]} to {pts[-1][0]}")
            print(f"Total {sum(g for _, g in pts):.0f} gal")
            for start, gal in pts[-24:]:
                print(start.astimezone(LOCAL_TZ), gal)

    asyncio.run(_main())
