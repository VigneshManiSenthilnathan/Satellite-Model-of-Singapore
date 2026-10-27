"""Session-drop retry in data.bloomberg (P1.1), with a fake blpapi -- no Terminal needed."""

from types import SimpleNamespace

import pytest

from data import bloomberg
from data.bloomberg import (
    BloombergError,
    BloombergSecurityError,
    BloombergSession,
    BloombergSessionError,
    _with_session,
)

Event = SimpleNamespace(TIMEOUT=1, RESPONSE=2, PARTIAL_RESPONSE=3, SESSION_STATUS=4, REQUEST_STATUS=5)


class FakeMessage:
    def __init__(self, kind):
        self.kind = kind

    def messageType(self):
        return self.kind

    def hasElement(self, name):
        return False


class FakeEvent(list):
    def __init__(self, event_type, *kinds):
        super().__init__(FakeMessage(k) for k in kinds)
        self.type = event_type

    def eventType(self):
        return self.type


class FakeSession:
    def __init__(self, events):
        self.events = iter(events)

    def sendRequest(self, request):
        pass

    def nextEvent(self, timeout):
        return next(self.events)


@pytest.fixture
def fake_blpapi(monkeypatch):
    monkeypatch.setattr(bloomberg, "_blpapi", lambda: SimpleNamespace(Event=Event))


def _send(events):
    bbg = BloombergSession()
    bbg.session = FakeSession(events)
    return bbg.send(request=None)


@pytest.mark.parametrize("event", [
    FakeEvent(Event.SESSION_STATUS, "SessionConnectionDown"),
    FakeEvent(Event.SESSION_STATUS, "SessionTerminated"),
    FakeEvent(Event.REQUEST_STATUS, "RequestFailure"),
    FakeEvent(Event.TIMEOUT),
])
def test_send_raises_session_error_on_drop(fake_blpapi, event):
    with pytest.raises(BloombergSessionError):
        _send([FakeEvent(Event.PARTIAL_RESPONSE, "HistoricalDataResponse"), event])


def test_send_ignores_harmless_status(fake_blpapi):
    messages = _send([FakeEvent(Event.SESSION_STATUS, "SessionConnectionUp"),
                      FakeEvent(Event.RESPONSE, "HistoricalDataResponse")])
    assert [m.kind for m in messages] == ["SessionConnectionUp", "HistoricalDataResponse"]


@pytest.fixture
def opened(monkeypatch):
    """Replace BloombergSession with a dummy and record how many sessions were opened."""
    count = {"n": 0}

    class DummySession:
        def __enter__(self):
            count["n"] += 1
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(bloomberg, "BloombergSession", DummySession)
    monkeypatch.setattr(bloomberg.time, "sleep", lambda s: None)
    return count


def _flaky(failures, exc=BloombergSessionError):
    calls = {"n": 0}

    def pull(bbg):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise exc("dropped")
        return "rows"
    return pull


def test_retries_until_success(opened):
    assert _with_session(_flaky(bloomberg.RETRIES - 1), session=None) == "rows"
    assert opened["n"] == bloomberg.RETRIES


def test_gives_up_after_retries(opened):
    with pytest.raises(BloombergSessionError):
        _with_session(_flaky(bloomberg.RETRIES), session=None)
    assert opened["n"] == bloomberg.RETRIES


@pytest.mark.parametrize("exc", [BloombergSecurityError, BloombergError])
def test_other_errors_not_retried(opened, exc):
    with pytest.raises(exc):
        _with_session(_flaky(1, exc), session=None)
    assert opened["n"] == 1


def test_caller_session_not_retried(opened):
    with pytest.raises(BloombergSessionError):
        _with_session(_flaky(1), session=object())
    assert opened["n"] == 0
