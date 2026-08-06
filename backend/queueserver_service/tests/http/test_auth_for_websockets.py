import json
import pprint
import threading
import time as ttime

import pytest
from starlette.websockets import WebSocket
from tests.manager.common import re_manager, re_manager_cmd, re_manager_factory  # noqa F401
from websockets.sync.client import connect

from .conftest import fastapi_server_fs  # noqa: F401
from .conftest import (
    SERVER_ADDRESS,
    SERVER_PORT,
    request_to_json,
    setup_server_with_config_file,
    wait_for_environment_to_be_closed,
    wait_for_environment_to_be_created,
)

config_toy_test = """
authentication:
    allow_anonymous_access: True
    providers:
        - provider: toy
          authenticator: queueserver_service.http.authenticators:DictionaryAuthenticator
          args:
              users_to_passwords:
                  bob: bob_password
                  alice: alice_password
                  cara: cara_password
                  tom: tom_password
api_access:
  policy: queueserver_service.http.authorization:DictionaryAPIAccessControl
  args:
    users:
      bob:
        roles:
          - admin
          - expert
      alice:
        roles: advanced
      tom:
        roles: user
"""


class _ReceiveSystemInfoSocket(threading.Thread):
    """
    Catch streaming console output by connecting to /console_output/ws socket and
    save messages to the buffer.
    """

    def __init__(self, *, endpoint, api_key=None, token=None, **kwargs):
        super().__init__(**kwargs)
        self.received_data_buffer = []
        self._exit = False
        self._api_key = api_key
        self._token = token
        self._endpoint = endpoint

    def run(self):
        websocket_uri = f"ws://{SERVER_ADDRESS}:{SERVER_PORT}/api{self._endpoint}"
        if self._token is not None:
            additional_headers = {"Authorization": f"Bearer {self._token}"}
        elif self._api_key is not None:
            additional_headers = {"Authorization": f"ApiKey {self._api_key}"}
        else:
            additional_headers = {}

        try:
            with connect(websocket_uri, additional_headers=additional_headers) as websocket:
                while not self._exit:
                    try:
                        msg_json = websocket.recv(timeout=0.1, decode=False)
                        try:
                            msg = json.loads(msg_json)
                            self.received_data_buffer.append(msg)
                        except json.JSONDecodeError:
                            pass
                    except TimeoutError:
                        pass
        except Exception as ex:
            print(f"Failed to connect to server: {ex}")

    def stop(self):
        """
        Call this method to stop the thread. Then send a request to the server so that some output
        is printed in ``stdout``.
        """
        self._exit = True

    def __del__(self):
        self.stop()


# fmt: off
@pytest.mark.parametrize("ws_auth_type", ["apikey", "apikey_invalid", "none"])
# fmt: on
def test_websocket_auth_01(
    tmpdir,
    monkeypatch,
    re_manager_cmd,  # noqa: F811
    fastapi_server_fs,  # noqa: F811
    ws_auth_type,
):
    """
    Test authentication for websockets. The test is run only on ``/status/ws`` websocket.
    The other websockets are expected to use the same authentication scheme.
    """

    # Start RE Manager
    params = ["--zmq-publish-console", "ON"]
    re_manager_cmd(params)

    setup_server_with_config_file(config_file_str=config_toy_test, tmpdir=tmpdir, monkeypatch=monkeypatch)
    fastapi_server_fs()

    resp1 = request_to_json("post", "/auth/provider/toy/token", login=("bob", "bob_password"))
    assert "access_token" in pprint.pformat(resp1)
    token = resp1["access_token"]

    resp3 = request_to_json(
        "post", "/auth/apikey", json={"expires_in": 900, "note": "API key for testing"}, token=token
    )
    assert "secret" in resp3, pprint.pformat(resp3)
    assert "note" in resp3, pprint.pformat(resp3)
    assert resp3["note"] == "API key for testing"
    assert resp3["scopes"] == ["inherit"]
    api_key = resp3["secret"]

    endpoint = "/status/ws"
    if ws_auth_type == "none":
        ws_params = {}
    elif ws_auth_type == "apikey":
        ws_params = {"api_key": api_key}
    elif ws_auth_type == "apikey_invalid":
        ws_params = {"api_key": "InvalidApiKey"}
    # elif ws_auth_type == "token":
    #     ws_params = {"token": token}
    # elif ws_auth_type == "token_invalid":
    #     ws_params = {"token": "InvalidToken"}
    else:
        assert False, f"Unknown authentication type: {ws_auth_type!r}"

    rsc = _ReceiveSystemInfoSocket(endpoint=endpoint, **ws_params)
    rsc.start()
    ttime.sleep(1)  # Wait until the client connects to the socket

    resp1 = request_to_json("post", "/environment/open", api_key=api_key)
    assert resp1["success"] is True, pprint.pformat(resp1)

    assert wait_for_environment_to_be_created(timeout=10, api_key=api_key)

    resp2b = request_to_json("post", "/environment/close", api_key=api_key)
    assert resp2b["success"] is True, pprint.pformat(resp2b)

    assert wait_for_environment_to_be_closed(timeout=10, api_key=api_key)

    # Wait until capture is complete
    ttime.sleep(2)
    rsc.stop()
    rsc.join()

    buffer = rsc.received_data_buffer
    if ws_auth_type in ("none", "apikey_invalid", "token_invalid"):
        assert len(buffer) == 0
    elif ws_auth_type in ("apikey", "token"):
        assert len(buffer) > 0
        for msg in buffer:
            assert "time" in msg, msg
            assert isinstance(msg["time"], float), msg
            assert "msg" in msg
            assert isinstance(msg["msg"], dict)
    else:
        assert False, f"Unknown authentication type: {ws_auth_type!r}"


def _make_websocket(app, *, query_string=b"", headers=None):
    """Build a minimal Starlette WebSocket for a /status/ws handshake scope."""
    scope = {
        "type": "websocket",
        "path": "/api/status/ws",
        "query_string": query_string,
        "headers": headers or [],
        "app": app,
    }
    return WebSocket(scope, receive=None, send=None)


# fmt: off
@pytest.mark.parametrize("scheme", ["ApiKey", "Apikey", "apikey", "aPiKeY", "APIKEY"])
# fmt: on
def test_websocket_apikey_header_case_insensitive(monkeypatch, scheme):
    """
    The API-key scheme name in the WebSocket 'Authorization' header must be accepted
    case-insensitively, matching the HTTP path — a client's header casing must not
    decide whether a WebSocket authenticates.
    """
    from queueserver_service.http import authentication as auth

    captured = {}

    def _fake_get_current_principal(*, api_key, access_token, **kwargs):
        captured["api_key"] = api_key
        captured["access_token"] = access_token
        return object() if api_key else None

    monkeypatch.setattr(auth, "get_current_principal", _fake_get_current_principal)

    class _App:
        dependency_overrides = {
            auth.get_settings: lambda: object(),
            auth.get_authenticators: lambda: {},
            auth.get_api_access_manager: lambda: object(),
        }

    ws = _make_websocket(_App(), headers=[(b"authorization", f"{scheme} SECRET".encode())])
    principal = auth.get_current_principal_websocket(websocket=ws, scopes=["read:monitor"])
    assert captured["api_key"] == "SECRET"
    assert principal is not None


def test_websocket_apikey_query_and_precedence(monkeypatch):
    """
    The API key may also be supplied as an '?api_key=' query parameter (matching the
    HTTP path). The 'Authorization' header takes precedence when both are present.
    A 'Bearer' token is not accepted as an API key.
    """
    from queueserver_service.http import authentication as auth

    captured = {}

    def _fake_get_current_principal(*, api_key, access_token, decoded_access_token=None, **kwargs):
        captured["api_key"] = api_key
        captured["access_token"] = access_token
        captured["decoded_access_token"] = decoded_access_token
        return object() if api_key else None

    monkeypatch.setattr(auth, "get_current_principal", _fake_get_current_principal)

    # Direct WS calls decode the Bearer token themselves (the FastAPI
    # ``decoded_access_token`` dependency is not injected outside routes) —
    # regression guard: leaving it at the Depends(...) default broke WS
    # Bearer auth by routing the sentinel object into the token branch.
    def _fake_decode_token(token, secret_keys, proxied_authenticator=None):
        if token == "SOME.JWT.TOKEN":
            return {"sub": "decoded-subject"}
        raise auth.ExpiredSignatureError("bad token")

    monkeypatch.setattr(auth, "decode_token", _fake_decode_token)

    from types import SimpleNamespace

    class _App:
        dependency_overrides = {
            auth.get_settings: lambda: SimpleNamespace(secret_keys=["test-secret"], authenticator=None),
            auth.get_authenticators: lambda: {},
            auth.get_api_access_manager: lambda: object(),
        }

    app = _App()

    # Key from the query parameter (no Authorization header).
    ws = _make_websocket(app, query_string=b"api_key=QUERYKEY")
    assert auth.get_current_principal_websocket(websocket=ws, scopes=["read:monitor"]) is not None
    assert captured["api_key"] == "QUERYKEY"

    # Header wins over query when both are present.
    ws = _make_websocket(
        app, query_string=b"api_key=QUERYKEY", headers=[(b"authorization", b"ApiKey HEADERKEY")]
    )
    auth.get_current_principal_websocket(websocket=ws, scopes=["read:monitor"])
    assert captured["api_key"] == "HEADERKEY"

    # A Bearer token is forwarded as an access token — decoded — never as an
    # API key. (Bearer support on WebSockets arrived with the tiled-aligned
    # auth stack — upstream PR #81; previously bearer auth was unsupported
    # on this path.)
    ws = _make_websocket(app, headers=[(b"authorization", b"Bearer SOME.JWT.TOKEN")])
    assert auth.get_current_principal_websocket(websocket=ws, scopes=["read:monitor"]) is None
    assert captured["api_key"] is None
    assert captured["access_token"] == "SOME.JWT.TOKEN"
    assert captured["decoded_access_token"] == {"sub": "decoded-subject"}

    # An invalid/expired Bearer token fails closed before reaching principal
    # resolution.
    captured.clear()
    ws = _make_websocket(app, headers=[(b"authorization", b"Bearer BAD.TOKEN")])
    assert auth.get_current_principal_websocket(websocket=ws, scopes=["read:monitor"]) is None
    assert captured == {}

    # No credentials at all -> no key.
    ws = _make_websocket(app)
    assert auth.get_current_principal_websocket(websocket=ws, scopes=["read:monitor"]) is None
    assert captured == {}


# ============================================================================
# First-message WebSocket auth handshake (upstream PR #81 parity)
# ============================================================================

from unittest.mock import MagicMock  # noqa: E402

from sqlalchemy.orm import sessionmaker  # noqa: E402

from queueserver_service.http import authentication as _auth  # noqa: E402
from queueserver_service.http.database import orm as db_orm  # noqa: E402
from queueserver_service.http.database.core import create_user  # noqa: E402




def _fake_ws_with_deps(*, api_access_manager=None, authenticators=None, settings=None):
    """Build a minimal fake WebSocket whose ``app.dependency_overrides``
    look like what build_app() installs at runtime, so
    ``authenticate_websocket_first_message`` can retrieve them."""

    from queueserver_service.http.settings import get_settings
    from queueserver_service.http.utils import (
        get_api_access_manager,
        get_authenticators,
    )

    class _App:
        state = MagicMock()
        dependency_overrides = {
            get_settings: lambda: settings,
            get_authenticators: lambda: authenticators or {},
            get_api_access_manager: lambda: api_access_manager,
        }

    class _WS:
        app = _App()
        headers = {"host": "localhost:8000"}
        scope = {"scheme": "http", "root_path": ""}
        query_params: dict = {}
        cookies: dict = {}

        def __init__(self):
            # get_current_principal reads request.state.cookies_to_set for a
            # side-effect on the HTTP path.  Provide a stub so that path does
            # not attribute-error on the websocket route.
            self.state = MagicMock()
            self.state.cookies_to_set = []

    return _WS()


def test_authenticate_websocket_first_message_rejects_non_auth_frames():
    ws = _fake_ws_with_deps(settings=MagicMock())
    assert _auth.authenticate_websocket_first_message(ws, {"type": "ping"}) is None
    assert _auth.authenticate_websocket_first_message(ws, "not-a-dict") is None
    assert _auth.authenticate_websocket_first_message(ws, {"type": "auth"}) is None


def test_authenticate_websocket_first_message_accepts_valid_api_key(sqlite_session):
    """Feed a valid API key through the first-message handshake."""
    from queueserver_service.http.settings import DatabaseSettings

    db = sqlite_session
    principal = create_user(db, "internal", "alice")
    # Generate an API key with the same machinery routes use.
    import hashlib
    import secrets as py_secrets

    secret = py_secrets.token_bytes(4 + 32)
    hashed = hashlib.sha256(secret).digest()
    apikey_orm = db_orm.APIKey(
        principal_id=principal.id,
        first_eight=secret.hex()[:8],
        hashed_secret=hashed,
        scopes=["read:status"],
    )
    db.add(apikey_orm)
    db.commit()

    # Route the sessionmaker used by get_current_principal through our
    # in-memory sqlite engine.
    engine = db.get_bind()

    def _fake_sessionmaker(_db_settings):
        return sessionmaker(bind=engine, autocommit=False, autoflush=False)

    settings = MagicMock()
    settings.database_settings = DatabaseSettings(uri="sqlite://", pool_size=None, pool_pre_ping=None)
    settings.authentication_provider_names = ["internal"]
    settings.secret_keys = ["hmac"]

    api_access_manager = MagicMock()
    api_access_manager.is_user_known.return_value = True
    api_access_manager.get_user_scopes.return_value = {"read:status"}
    api_access_manager.get_user_roles.return_value = {"user"}

    authenticators = {"internal": MagicMock()}  # truthy => multi-user mode
    ws = _fake_ws_with_deps(
        api_access_manager=api_access_manager, authenticators=authenticators, settings=settings
    )

    import queueserver_service.http.authentication as auth_mod

    saved = auth_mod.get_sessionmaker
    auth_mod.get_sessionmaker = _fake_sessionmaker
    try:
        result = _auth.authenticate_websocket_first_message(ws, {"type": "auth", "api_key": secret.hex()})
    finally:
        auth_mod.get_sessionmaker = saved

    assert result is not None
    assert result.uuid == principal.uuid


def test_authenticate_websocket_first_message_rejects_bad_api_key(sqlite_session):
    """A malformed (non-hex) API key must be rejected without leaking DB
    state.  Uses the same monkey-patched sessionmaker plumbing as the
    happy-path test so we do not accidentally exercise the real
    get_sessionmaker(pool_size=None) code path in unit tests."""
    from queueserver_service.http.settings import DatabaseSettings

    engine = sqlite_session.get_bind()

    def _fake_sessionmaker(_db_settings):
        return sessionmaker(bind=engine, autocommit=False, autoflush=False)

    settings = MagicMock()
    settings.database_settings = DatabaseSettings(uri="sqlite://", pool_size=5, pool_pre_ping=False)
    settings.authentication_provider_names = ["internal"]
    settings.secret_keys = ["hmac"]

    ws = _fake_ws_with_deps(
        api_access_manager=MagicMock(),
        authenticators={"internal": MagicMock()},
        settings=settings,
    )

    import queueserver_service.http.authentication as auth_mod

    saved = auth_mod.get_sessionmaker
    auth_mod.get_sessionmaker = _fake_sessionmaker
    try:
        # 'not-hex' fails bytes.fromhex → HTTPException 401 inside get_current_principal.
        assert _auth.authenticate_websocket_first_message(ws, {"type": "auth", "api_key": "not-hex"}) is None
    finally:
        auth_mod.get_sessionmaker = saved
