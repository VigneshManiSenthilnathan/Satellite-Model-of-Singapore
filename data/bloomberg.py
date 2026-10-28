"""Bloomberg Desktop API wrapper with a local parquet cache (plan tasks P1.1-P1.2).

Every pull is written to the cache before it is returned, so the same request
is never sent to Bloomberg twice unless ``refresh=True``.

Cache layout (git-ignored, never commit -- Bloomberg licensing):

    data/raw/bloomberg/vintage=YYYY-MM-DD/{kind}_{key}.parquet   data
    data/raw/bloomberg/vintage=YYYY-MM-DD/{kind}_{key}.json      request + pull metadata

``key`` is a hash of the request (tickers, fields, dates, options), so any
change to the request is a cache miss. A cache hit returns the most recent
vintage holding that key. Requests with ``end=None`` resolve to today's date,
so open-ended history pulls refresh at most once a day.

Vintages (P1.3): pass ``vintage="YYYY-MM-DD"`` to bdh/bdp to read the data as
it stood on that date -- the newest cached copy at or before that vintage,
with ``end=None`` meaning the vintage date. Vintage reads are cache-only: they
never call Bloomberg and raise FileNotFoundError if the data was not pulled.
``list_vintages()`` lists the dates available.

Usage:
    from data.bloomberg import bdh, bdp
    df = bdh(["USGG3M Index"], ["PX_LAST"], "2000-01-01", periodicity="QUARTERLY")
    ref = bdp(["USGG3M Index"], ["NAME", "SECURITY_DES"])
    old = bdh(["USGG3M Index"], ["PX_LAST"], "2000-01-01", periodicity="QUARTERLY", vintage="2026-10-27")
"""

import datetime as dt
import hashlib
import json
import logging
import time
from pathlib import Path

import pandas as pd

from data.panel import SYNTHETIC_ENV, synthetic_mode

log = logging.getLogger(__name__)

HOST = "localhost"
PORT = 8194
TIMEOUT_MS = 30_000
RETRIES = 3            # attempts per request when the session drops (P1.1)
RETRY_WAIT_S = 2.0     # wait before retry n is RETRY_WAIT_S * 2**(n-1)
DROP_MESSAGES = {"SessionConnectionDown", "SessionTerminated", "RequestFailure"}
CACHE_DIR = Path(__file__).resolve().parent / "raw" / "bloomberg"

HISTORICAL_OPTIONS = {
    "periodicitySelection",      # DAILY, WEEKLY, MONTHLY, QUARTERLY, SEMI_ANNUALLY, YEARLY
    "periodicityAdjustment",     # ACTUAL, CALENDAR, FISCAL
    "nonTradingDayFillOption",   # NON_TRADING_WEEKDAYS, ALL_CALENDAR_DAYS, ACTIVE_DAYS_ONLY
    "nonTradingDayFillMethod",   # PREVIOUS_VALUE, NIL_VALUE
    "currency",
    "pricingOption",
    "adjustmentNormal",
    "adjustmentAbnormal",
    "adjustmentSplit",
}


class BloombergError(RuntimeError):
    """Connection, service or request failure."""


class BloombergSecurityError(BloombergError):
    """Every requested security was rejected (bad ticker or no entitlement)."""


class BloombergSessionError(BloombergError):
    """The session failed to start, dropped, or timed out. Retried by the request functions."""


# --------------------------------------------------------------------------- cache

def _date_str(value):
    if value is None:
        return dt.date.today().strftime("%Y%m%d")
    return pd.Timestamp(value).strftime("%Y%m%d")


def _request_key(spec):
    canonical = json.dumps(spec, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _vintage_str(value):
    return pd.Timestamp(value).date().isoformat()


def _cache_lookup(kind, key, as_of=None):
    """Newest cached file for this request, optionally restricted to vintages <= as_of."""
    hits = sorted(CACHE_DIR.glob(f"vintage=*/{kind}_{key}.parquet"))
    if as_of is not None:
        # Folder names are vintage=YYYY-MM-DD, so string order is date order.
        hits = [h for h in hits if h.parent.name <= f"vintage={_vintage_str(as_of)}"]
    return hits[-1] if hits else None


def _vintage_read(kind, key, vintage, spec):
    path = _cache_lookup(kind, key, as_of=vintage)
    if path is None:
        raise FileNotFoundError(
            f"No cached {kind} data at or before vintage {_vintage_str(vintage)} for request {spec}"
        )
    return _cache_read(path)


def list_vintages():
    """Vintage dates present in the cache, oldest first (as 'YYYY-MM-DD' strings)."""
    return sorted(p.name.removeprefix("vintage=") for p in CACHE_DIR.glob("vintage=*") if p.is_dir())


def _normalise(df):
    # Parquet round-trips datetimes at a coarser unit; fix one so live and cached frames match.
    if "date" in df:
        df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    return df


def _cache_read(path):
    return _normalise(pd.read_parquet(path))


def _cache_write(kind, key, df, spec, warnings):
    folder = CACHE_DIR / f"vintage={dt.date.today().isoformat()}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{kind}_{key}.parquet"
    df.to_parquet(path, index=False)
    meta = {
        "kind": kind,
        "request": spec,
        "pulled_at": dt.datetime.now().isoformat(timespec="seconds"),
        "rows": len(df),
        "warnings": warnings,
        "blpapi_version": _blpapi().__version__,
    }
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2, default=str))
    return path


def cache_info(kind, key):
    """Return the metadata dict for a cached request, or None."""
    path = _cache_lookup(kind, key)
    if path is None:
        return None
    return json.loads(path.with_suffix(".json").read_text())


# --------------------------------------------------------------------------- session

def _blpapi():
    try:
        import blpapi
    except ImportError as exc:
        raise BloombergError(
            "blpapi not installed; run: pip install --index-url="
            "https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi"
        ) from exc
    return blpapi


class BloombergSession:
    """Context manager around a Desktop API session with //blp/refdata open."""

    def __init__(self, host=HOST, port=PORT):
        self.host = host
        self.port = port
        self.session = None
        self.service = None

    def __enter__(self):
        if synthetic_mode():
            raise BloombergError(f"Bloomberg is disabled in synthetic mode ({SYNTHETIC_ENV} is set).")
        blpapi = _blpapi()
        options = blpapi.SessionOptions()
        options.setServerHost(self.host)
        options.setServerPort(self.port)
        self.session = blpapi.Session(options)
        if not self.session.start():
            raise BloombergSessionError(
                f"Could not connect to {self.host}:{self.port}. Is the Terminal open and logged in?"
            )
        if not self.session.openService("//blp/refdata"):
            self.session.stop()
            raise BloombergError("Could not open //blp/refdata. Check API access for this login.")
        self.service = self.session.getService("//blp/refdata")
        return self

    def __exit__(self, *exc):
        if self.session is not None:
            self.session.stop()

    def other_service(self, name):
        """Open and return another service on this session, e.g. //blp/instruments."""
        if not self.session.openService(name):
            raise BloombergError(f"Could not open {name}.")
        return self.session.getService(name)

    def send(self, request):
        """Send a request and return every message up to the final RESPONSE."""
        blpapi = _blpapi()
        self.session.sendRequest(request)
        messages = []
        while True:
            event = self.session.nextEvent(TIMEOUT_MS)
            if event.eventType() == blpapi.Event.TIMEOUT:
                raise BloombergSessionError(f"Timed out after {TIMEOUT_MS / 1000:.0f}s waiting for Bloomberg")
            status = event.eventType() in (blpapi.Event.SESSION_STATUS, blpapi.Event.REQUEST_STATUS)
            for msg in event:
                if status and str(msg.messageType()) in DROP_MESSAGES:
                    raise BloombergSessionError(f"Session dropped: {msg.messageType()}")
                if msg.hasElement("responseError"):
                    raise BloombergError(str(msg.getElement("responseError")))
                messages.append(msg)
            if event.eventType() == blpapi.Event.RESPONSE:
                return messages


def _field_exceptions(sec, ticker):
    if not sec.hasElement("fieldExceptions"):
        return []
    out = []
    for fe in sec.getElement("fieldExceptions").values():
        info = fe.getElement("errorInfo")
        out.append(f"{ticker} {fe.getElementAsString('fieldId')}: {info.getElementAsString('message')}")
    return out


def _clean_values(df):
    # Keep numeric fields numeric; fall back to strings so parquet can store mixed fields.
    numeric = pd.to_numeric(df["value"], errors="coerce")
    if numeric.notna().sum() == df["value"].notna().sum():
        df["value"] = numeric
    else:
        df["value"] = df["value"].astype("string")
    return df


def _with_session(pull, session):
    """Run pull(bbg) on the caller's session, or on a fresh one that is reopened if it drops.

    A caller-supplied session is never retried: it can't be reopened here, so the
    BloombergSessionError goes back to the caller.
    """
    if session is not None:
        return pull(session)
    for attempt in range(1, RETRIES + 1):
        try:
            with BloombergSession() as bbg:
                return pull(bbg)
        except BloombergSessionError as exc:
            if attempt == RETRIES:
                raise
            wait = RETRY_WAIT_S * 2 ** (attempt - 1)
            log.warning("%s; retrying in %.0fs (attempt %d of %d)", exc, wait, attempt + 1, RETRIES)
            time.sleep(wait)


# --------------------------------------------------------------------------- requests

def _bdh_spec(tickers, fields, start, end, periodicity, overrides, vintage, options):
    """The cache-key request spec for bdh. With a vintage, end=None means the vintage date."""
    unknown = set(options) - HISTORICAL_OPTIONS
    if unknown:
        raise ValueError(f"Unknown HistoricalDataRequest options: {sorted(unknown)}")
    return {
        "tickers": sorted(tickers),
        "fields": sorted(fields),
        "start": _date_str(start),
        "end": _date_str(end if end is not None or vintage is None else vintage),
        "options": {"periodicitySelection": periodicity, **options},
        "overrides": overrides or {},
    }


def bdh(tickers, fields, start, end=None, periodicity="DAILY", overrides=None,
        refresh=False, session=None, vintage=None, **options):
    """Historical data. Returns a long DataFrame: date, ticker, field, value.

    Extra keyword options are passed to HistoricalDataRequest (see HISTORICAL_OPTIONS).
    vintage="YYYY-MM-DD" reads that vintage from the cache only (see module docstring).
    """
    tickers = [tickers] if isinstance(tickers, str) else list(tickers)
    fields = [fields] if isinstance(fields, str) else list(fields)
    if vintage is not None and refresh:
        raise ValueError("vintage reads are cache-only; refresh=True can't be combined with vintage")
    spec = _bdh_spec(tickers, fields, start, end, periodicity, overrides, vintage, options)
    options = spec["options"]
    key = _request_key(spec)
    if vintage is not None:
        return _vintage_read("bdh", key, vintage, spec)
    cached = None if refresh else _cache_lookup("bdh", key)
    if cached is not None:
        return _cache_read(cached)

    def pull(bbg):
        request = bbg.service.createRequest("HistoricalDataRequest")
        for t in tickers:
            request.getElement("securities").appendValue(t)
        for f in fields:
            request.getElement("fields").appendValue(f)
        request.set("startDate", spec["start"])
        request.set("endDate", spec["end"])
        for name, value in options.items():
            request.set(name, value)
        for field_id, value in (overrides or {}).items():
            ov = request.getElement("overrides").appendElement()
            ov.setElement("fieldId", field_id)
            ov.setElement("value", str(value))

        rows, warnings, bad = [], [], []
        for msg in bbg.send(request):
            if not msg.hasElement("securityData"):
                continue
            sec = msg.getElement("securityData")
            ticker = sec.getElementAsString("security")
            if sec.hasElement("securityError"):
                bad.append(f"{ticker}: {sec.getElement('securityError').getElementAsString('message')}")
                continue
            warnings.extend(_field_exceptions(sec, ticker))
            for row in sec.getElement("fieldData").values():
                date = row.getElementAsDatetime("date")
                for f in fields:
                    if row.hasElement(f):
                        rows.append((date, ticker, f, row.getElement(f).getValue()))
        return rows, warnings, bad

    rows, warnings, bad = _with_session(pull, session)

    if bad and len(bad) == len(tickers):
        raise BloombergSecurityError("; ".join(bad))
    warnings.extend(f"security error {b}" for b in bad)
    df = pd.DataFrame(rows, columns=["date", "ticker", "field", "value"])
    df = _clean_values(_normalise(df))
    _cache_write("bdh", key, df, spec, warnings)
    return df


def bdp(tickers, fields, overrides=None, refresh=False, session=None, vintage=None):
    """Reference data. Returns a long DataFrame: ticker, field, value.

    Reference data is cached by request only (no date in the key), so pass
    refresh=True to re-pull fields that change over time.
    vintage="YYYY-MM-DD" reads that vintage from the cache only.
    """
    tickers = [tickers] if isinstance(tickers, str) else list(tickers)
    fields = [fields] if isinstance(fields, str) else list(fields)
    if vintage is not None and refresh:
        raise ValueError("vintage reads are cache-only; refresh=True can't be combined with vintage")
    spec = {"tickers": sorted(tickers), "fields": sorted(fields), "overrides": overrides or {}}
    key = _request_key(spec)
    if vintage is not None:
        return _vintage_read("bdp", key, vintage, spec)
    cached = None if refresh else _cache_lookup("bdp", key)
    if cached is not None:
        return _cache_read(cached)

    def pull(bbg):
        request = bbg.service.createRequest("ReferenceDataRequest")
        for t in tickers:
            request.getElement("securities").appendValue(t)
        for f in fields:
            request.getElement("fields").appendValue(f)
        for field_id, value in (overrides or {}).items():
            ov = request.getElement("overrides").appendElement()
            ov.setElement("fieldId", field_id)
            ov.setElement("value", str(value))

        rows, warnings, bad = [], [], []
        for msg in bbg.send(request):
            if not msg.hasElement("securityData"):
                continue
            for sec in msg.getElement("securityData").values():
                ticker = sec.getElementAsString("security")
                if sec.hasElement("securityError"):
                    bad.append(f"{ticker}: {sec.getElement('securityError').getElementAsString('message')}")
                    continue
                warnings.extend(_field_exceptions(sec, ticker))
                data = sec.getElement("fieldData")
                for f in fields:
                    if data.hasElement(f):
                        rows.append((ticker, f, str(data.getElement(f).getValue())))
        return rows, warnings, bad

    rows, warnings, bad = _with_session(pull, session)

    if bad and len(bad) == len(tickers):
        raise BloombergSecurityError("; ".join(bad))
    warnings.extend(f"security error {b}" for b in bad)
    df = pd.DataFrame(rows, columns=["ticker", "field", "value"]).astype("string")
    _cache_write("bdp", key, df, spec, warnings)
    return df


# --------------------------------------------------------------------------- discovery

def search_instruments(query, yellow_key="YK_FILTER_INDX", max_results=25,
                       refresh=False, session=None):
    """Ticker search (the API equivalent of SECF). Returns: ticker, description.

    yellow_key: YK_FILTER_INDX, YK_FILTER_EQTY, YK_FILTER_CRNY, YK_FILTER_GOVT, YK_FILTER_NONE ...
    Results are cached like any other pull.
    """
    spec = {"query": query, "yellow_key": yellow_key, "max_results": max_results}
    key = _request_key(spec)
    cached = None if refresh else _cache_lookup("search", key)
    if cached is not None:
        return _cache_read(cached)

    def pull(bbg):
        service = bbg.other_service("//blp/instruments")
        request = service.createRequest("instrumentListRequest")
        request.set("query", query)
        request.set("yellowKeyFilter", yellow_key)
        request.set("maxResults", max_results)
        rows = []
        for msg in bbg.send(request):
            if not msg.hasElement("results"):
                continue
            for item in msg.getElement("results").values():
                # Search returns "TICKER<index>"; convert to "TICKER Index" API form.
                sec = item.getElementAsString("security")
                if "<" in sec:
                    code, yk = sec.rstrip(">").split("<")
                    sec = f"{code} {yk.capitalize()}"
                rows.append((sec, item.getElementAsString("description")))
        return rows

    rows = _with_session(pull, session)
    df = pd.DataFrame(rows, columns=["ticker", "description"]).astype("string")
    _cache_write("search", key, df, spec, [])
    return df


def search_fields(query, refresh=False, session=None):
    """Field search (the API equivalent of FLDS). Returns: mnemonic, description."""
    spec = {"query": query}
    key = _request_key(spec)
    cached = None if refresh else _cache_lookup("flds", key)
    if cached is not None:
        return _cache_read(cached)

    def pull(bbg):
        service = bbg.other_service("//blp/apiflds")
        request = service.createRequest("FieldSearchRequest")
        request.set("searchSpec", query)
        rows = []
        for msg in bbg.send(request):
            if not msg.hasElement("fieldData"):
                continue
            for fd in msg.getElement("fieldData").values():
                if not fd.hasElement("fieldInfo"):
                    continue
                info = fd.getElement("fieldInfo")
                rows.append((info.getElementAsString("mnemonic"), info.getElementAsString("description")))
        return rows

    rows = _with_session(pull, session)
    df = pd.DataFrame(rows, columns=["mnemonic", "description"]).astype("string")
    _cache_write("flds", key, df, spec, [])
    return df
