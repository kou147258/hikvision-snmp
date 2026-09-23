"""Tests for the per-host SNMP client wrapper.

Coverage spans three releases:

- **v0.1.11** — ``timeout`` / ``retries`` are constructor kwargs (no
  more ``client._target.__class__((host, port), timeout=3, retries=2)``
  round-trip that some pysnmp 6.x builds reject as ``got multiple
  values for argument 'timeout'``).
- **v0.1.12** — ``SnmpEngine()`` is lazy and constructed in
  ``asyncio.to_thread`` so HA's blocking-call detector stops
  flagging ``os.listdir`` / ``open`` against pysnmp's MIB directory.
- **v0.1.13** — ``UdpTransportTarget`` is also lazy, and the
  construction dispatches between the pysnmp 6.x synchronous API
  and the pysnmp 7.x ``UdpTransportTarget.create(...)`` async API
  via a runtime signature check. HAOS 2026.x ships Python 3.14 with
  pysnmp 7.x at the system level (``/usr/local/lib/python3.14/site-packages/pysnmp/``),
  which the integration's manifest pin ``pysnmp<7.0.0`` doesn't
  override — so we have to support both APIs.
"""

from __future__ import annotations

import asyncio as _asyncio

from custom_components.hikvision_snmp.const import (
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_RETRIES,
)
from custom_components.hikvision_snmp.snmp_client import HikvisionSnmpClient


def _reset_engine_singleton() -> None:
    """Reset module-level engine singleton + lock so tests are isolated."""
    import custom_components.hikvision_snmp.snmp_client as client_mod
    client_mod._ENGINE_SINGLETON = None
    client_mod._ENGINE_INIT_LOCK = None
    client_mod._UDP_TARGET_API = None


async def _build_target(client):
    """Async helper — drives ``_ensure_engine`` and returns the target."""
    await client._ensure_engine()
    return client._target


# ---- v0.1.11 — timeout/retries constructor kwargs ----


def test_construct_with_default_timeout_and_retries():
    """Defaults come from const.DEFAULT_REQUEST_TIMEOUT / DEFAULT_RETRIES."""
    client = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                                 auth={"community": "public"})
    target = _asyncio.run(_build_target(client))
    assert target.timeout == DEFAULT_REQUEST_TIMEOUT
    assert target.retries == DEFAULT_RETRIES


def test_construct_with_explicit_timeout_and_retries():
    """Explicit kwargs are passed through to UdpTransportTarget.

    This is the path the config-flow connection test relies on (v0.1.11+).
    """
    client = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                                 auth={"community": "public"},
                                 timeout=3, retries=2)
    target = _asyncio.run(_build_target(client))
    assert target.timeout == 3
    assert target.retries == 2


def test_construct_with_only_timeout():
    """``retries`` defaults when only ``timeout`` is overridden."""
    client = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                                 auth={"community": "public"},
                                 timeout=5)
    target = _asyncio.run(_build_target(client))
    assert target.timeout == 5
    assert target.retries == DEFAULT_RETRIES


def test_construct_with_only_retries():
    """``timeout`` defaults when only ``retries`` is overridden."""
    client = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                                 auth={"community": "public"},
                                 retries=4)
    target = _asyncio.run(_build_target(client))
    assert target.timeout == DEFAULT_REQUEST_TIMEOUT
    assert target.retries == 4


def test_construct_does_not_raise_abstract_transport_target_error():
    """Regression guard for the v0.1.10 bug.

    ``client._target.__class__((host, port), timeout=3, retries=2)`` used to
    raise ``TypeError: AbstractTransportTarget.__init__() got multiple values
    for argument 'timeout'`` on some pysnmp 6.x builds. Now we never call
    ``__class__()`` at all, so this guard exists to ensure a future refactor
    doesn't re-introduce the round-trip pattern.
    """
    client = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                                 auth={"community": "public"},
                                 timeout=3, retries=2)
    target = _asyncio.run(_build_target(client))
    assert target is not None
    assert isinstance(target.timeout, (int, float))
    assert isinstance(target.retries, int)


# ---- v0.1.12 — lazy / shared SnmpEngine ----
#
# Pre-v0.1.12 the constructor called ``self._engine = SnmpEngine()``
# directly, which is a synchronous call that does ``os.listdir`` and
# ``open`` against pysnmp's MIB directory. HA's event-loop blocking-call
# monitor flagged each one. The fix defers construction to ``_ensure_engine``
# (called from the request methods), runs it via ``asyncio.to_thread``, and
# shares one engine across every client.


def test_engine_not_constructed_in_sync_init():
    """Regression guard for v0.1.12 — ``SnmpEngine()`` is lazy.

    If this test ever fails because ``__init__`` started constructing the
    engine synchronously again, HA's event-loop blocking-call detector
    will start firing ``Detected blocking call to listdir with args
    ('/usr/local/lib/python3.14/site-packages/pysnmp/smi/mibs',)`` warnings
    again on every device the integration polls. Keep construction lazy.
    """
    _reset_engine_singleton()

    c = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                            auth={"community": "public"})
    assert c._engine is None
    # And the module-level singleton is also still None — nothing should
    # have triggered construction.
    import custom_components.hikvision_snmp.snmp_client as client_mod
    assert client_mod._ENGINE_SINGLETON is None


def test_engine_lazy_init_runs_in_to_thread():
    """First ``_ensure_engine`` runs ``SnmpEngine()`` inside ``asyncio.to_thread``.

    The point of the fix is that the synchronous ``os.listdir`` / ``open``
    pysnmp does in ``SnmpEngine.__init__`` happens off the HA event loop,
    so HA's blocking-call detector stops complaining.
    """
    from unittest.mock import patch

    _reset_engine_singleton()

    constructed_in_thread: list[bool] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        constructed_in_thread.append(True)
        return object()  # sentinel

    async def driver():
        c = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                                auth={"community": "public"})
        with patch.object(_asyncio, "to_thread", side_effect=fake_to_thread):
            engine = await c._ensure_engine()
        return engine

    engine = _asyncio.run(driver())
    assert constructed_in_thread == [True]
    assert engine is not None  # whatever fake_to_thread returned
    import custom_components.hikvision_snmp.snmp_client as client_mod
    assert client_mod._ENGINE_SINGLETON is not None


def test_clients_share_one_engine_singleton():
    """Multiple ``HikvisionSnmpClient`` instances reuse one ``SnmpEngine``.

    Constructing a fresh ``SnmpEngine`` is a ~480 ms blocking call
    (off-loop now, but still non-trivial). Sharing the singleton means
    N devices cost 480 ms total, not N × 480 ms.
    """
    _reset_engine_singleton()

    async def driver():
        c1 = HikvisionSnmpClient(host="10.0.0.1", port=161, version="v2c",
                                 auth={"community": "public"})
        c2 = HikvisionSnmpClient(host="10.0.0.2", port=161, version="v2c",
                                 auth={"community": "public"})
        e1 = await c1._ensure_engine()
        e2 = await c2._ensure_engine()
        return c1, c2, e1, e2

    c1, c2, e1, e2 = _asyncio.run(driver())
    assert c1 is not c2  # different client objects
    assert e1 is e2  # ... but the SAME SnmpEngine
    assert c1._engine is c2._engine  # cached on both clients


def test_close_is_noop_and_does_not_tear_down_shared_dispatcher():
    """``client.close()`` must not call ``closeDispatcher`` on the shared engine."""
    _reset_engine_singleton()

    async def driver():
        c = HikvisionSnmpClient(host="10.0.0.1", port=161, version="v2c",
                                auth={"community": "public"})
        await c._ensure_engine()
        before = c._engine
        await c.close()
        return before

    engine_before = _asyncio.run(driver())
    import custom_components.hikvision_snmp.snmp_client as client_mod
    assert engine_before is client_mod._ENGINE_SINGLETON
    assert client_mod._ENGINE_SINGLETON is not None


# ---- v0.1.13 — lazy / pysnmp-version-aware UdpTransportTarget ----
#
# HAOS 2026.x ships Python 3.14 with pysnmp 7.x pre-installed at the
# system level. pysnmp 7.x's ``UdpTransportTarget.__init__`` signature is
# ``(self, timeout=1, retries=5, tagList=b'')`` — completely incompatible
# with pysnmp 6.x's ``(self, transportAddr, timeout=1, retries=5, tagList=b'')``.
# Calling the 6.x pattern against pysnmp 7.x raises
# ``TypeError: AbstractTransportTarget.__init__() got multiple values for
# argument 'timeout'`` (positional `(host, port)` collides with the new
# `timeout` first arg).
#
# The fix detects the API at runtime via ``inspect.signature`` and adapts.


def test_target_not_constructed_in_sync_init():
    """Regression guard for v0.1.13 — ``UdpTransportTarget`` is lazy.

    If this test ever fails because ``__init__`` started constructing the
    target synchronously again, HAOS users with pysnmp 7.x will start
    seeing ``AbstractTransportTarget.__init__() got multiple values for
    argument 'timeout'`` errors at construction time again — pre-empting
    every config-flow connection test. Keep construction lazy.
    """
    _reset_engine_singleton()

    c = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                            auth={"community": "public"})
    assert c._target is None


def test_pysnmp_v6_api_uses_sync_constructor():
    """When pysnmp 6.x is installed, target is built with the legacy sync API.

    The detection logic caches ``_UDP_TARGET_API = "v6"`` the first time
    it's checked. With that cached, ``_build_udp_target`` returns a target
    via the synchronous ``UdpTransportTarget((host, port), ...)`` path
    — no ``await`` on the create() classmethod.
    """
    from unittest.mock import patch

    import custom_components.hikvision_snmp.snmp_client as client_mod

    class FakeV6UdpTarget:
        def __init__(self, addr, *, timeout, retries):
            self.addr = addr
            self.timeout = timeout
            self.retries = retries

    async def driver():
        c = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                                auth={"community": "public"},
                                timeout=3, retries=2)
        with patch.object(client_mod, "UdpTransportTarget", FakeV6UdpTarget):
            client_mod._UDP_TARGET_API = "v6"
            await c._ensure_engine()
        return c._target

    target = _asyncio.run(driver())
    assert isinstance(target, FakeV6UdpTarget)
    assert target.addr == ("127.0.0.1", 161)
    assert target.timeout == 3
    assert target.retries == 2


def test_pysnmp_v7_api_uses_async_create():
    """When pysnmp 7.x is installed, target is built via ``await UdpTransportTarget.create(...)``.

    The detection logic caches ``_UDP_TARGET_API = "v7"``. ``_build_udp_target``
    awaits ``UdpTransportTarget.create((host, port), ...)`` and returns the
    result — no positional ``UdpTransportTarget.__init__`` call.
    """
    from unittest.mock import patch

    import custom_components.hikvision_snmp.snmp_client as client_mod

    class FakeV7UdpTarget:
        """Mimics pysnmp 7.x's UdpTransportTarget with a .create() classmethod."""

        @classmethod
        async def create(cls, addr, *, timeout, retries):
            inst = cls()
            inst.addr = addr
            inst.timeout = timeout
            inst.retries = retries
            return inst

    async def driver():
        c = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                                auth={"community": "public"},
                                timeout=3, retries=2)
        with patch.object(client_mod, "UdpTransportTarget", FakeV7UdpTarget):
            client_mod._UDP_TARGET_API = "v7"
            await c._ensure_engine()
        return c._target

    target = _asyncio.run(driver())
    assert isinstance(target, FakeV7UdpTarget)
    assert target.addr == ("127.0.0.1", 161)
    assert target.timeout == 3
    assert target.retries == 2


def test_detection_picks_v6_when_transportAddr_in_signature():
    """``_detect_udp_target_api`` returns ``"v6"`` when ``transportAddr`` is a param.

    Simulates the pysnmp 6.x ``UdpTransportTarget.__init__`` signature.
    """
    from unittest.mock import patch

    import custom_components.hikvision_snmp.snmp_client as client_mod

    class FakeV6Ctor:
        def __init__(self, transportAddr, timeout=1, retries=5, tagList=b""):
            pass

    with patch.object(client_mod, "UdpTransportTarget", FakeV6Ctor):
        client_mod._UDP_TARGET_API = None
        assert client_mod._detect_udp_target_api() == "v6"
        assert client_mod._udp_target_api() == "v6"  # cached


def test_detection_picks_v7_when_transportAddr_missing():
    """``_detect_udp_target_api`` returns ``"v7"`` when ``transportAddr`` is absent.

    Simulates the pysnmp 7.x ``UdpTransportTarget.__init__`` signature
    ``(self, timeout=1, retries=5, tagList=b'')`` — the case where
    ``AbstractTransportTarget.__init__() got multiple values for argument
    'timeout'`` was raised at every config-flow test attempt on HAOS 2026.x.
    """
    from unittest.mock import patch

    import custom_components.hikvision_snmp.snmp_client as client_mod

    class FakeV7Ctor:
        def __init__(self, timeout=1, retries=5, tagList=b""):
            pass

    with patch.object(client_mod, "UdpTransportTarget", FakeV7Ctor):
        client_mod._UDP_TARGET_API = None
        assert client_mod._detect_udp_target_api() == "v7"
        assert client_mod._udp_target_api() == "v7"  # cached


def test_engine_and_target_built_in_same_ensure_call():
    """``_ensure_engine`` populates both ``_engine`` and ``_target`` in one call."""
    from unittest.mock import patch

    import custom_components.hikvision_snmp.snmp_client as client_mod

    class FakeUdpTarget:
        def __init__(self, addr, *, timeout, retries):
            self.timeout = timeout
            self.retries = retries

    async def driver():
        c = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                                auth={"community": "public"})
        with patch.object(client_mod, "UdpTransportTarget", FakeUdpTarget):
            client_mod._UDP_TARGET_API = "v6"
            await c._ensure_engine()
        return c._engine, c._target

    engine, target = _asyncio.run(driver())
    assert engine is not None
    assert target is not None
    assert isinstance(target, FakeUdpTarget)


# ---- v0.1.14 — pysnmp 7.x renamed get/bulk/next cmd functions too ----
#
# pysnmp 7.x renamed the cmd functions, not just the target:
#
#   pysnmp 6.x: getCmd, bulkCmd, nextCmd   (camelCase, top of module)
#   pysnmp 7.x: get_cmd, bulk_cmd, next_cmd   (snake_case)
#
# Using ``from pysnmp.hlapi.asyncio import bulkCmd, getCmd, nextCmd`` makes
# the entire ``snmp_client`` module fail to LOAD on pysnmp 7.x with
# ImportError — which breaks HA's integration loader, prevents
# config_flow.py from registering, and surfaces to the user as
# "无法加载配置向导: Invalid handler specified" when they try to add
# the integration. The fix is a runtime resolver that picks whichever
# naming convention the loaded pysnmp exposes.


def test_cmd_functions_resolve_to_camelcase_under_pysnmp_v6():
    """Under pysnmp 6.x, ``_resolve_cmd_functions`` returns the camelCase names."""
    import custom_components.hikvision_snmp.snmp_client as client_mod

    class FakeV6Hlapi:
        def getCmd(self): pass
        def bulkCmd(self): pass
        def nextCmd(self): pass

    real_hlapi = client_mod._pysnmp_hlapi
    try:
        client_mod._pysnmp_hlapi = FakeV6Hlapi
        get, bulk, nxt = client_mod._resolve_cmd_functions()
        assert get.__name__ == "getCmd"
        assert bulk.__name__ == "bulkCmd"
        assert nxt.__name__ == "nextCmd"
    finally:
        client_mod._pysnmp_hlapi = real_hlapi


def test_cmd_functions_resolve_to_snakecase_under_pysnmp_v7():
    """Under pysnmp 7.x, ``_resolve_cmd_functions`` returns the snake_case names.

    This is the path HAOS 2026.x hits because pysnmp 7.1.29 is pre-installed
    at ``/usr/local/lib/python3.14/site-packages/pysnmp/`` and the module
    load would ImportError on the camelCase ``from ... import`` statement.
    """
    import custom_components.hikvision_snmp.snmp_client as client_mod

    class FakeV7Hlapi:
        def get_cmd(self): pass
        def bulk_cmd(self): pass
        def next_cmd(self): pass

    real_hlapi = client_mod._pysnmp_hlapi
    try:
        client_mod._pysnmp_hlapi = FakeV7Hlapi
        get, bulk, nxt = client_mod._resolve_cmd_functions()
        assert get.__name__ == "get_cmd"
        assert bulk.__name__ == "bulk_cmd"
        assert nxt.__name__ == "next_cmd"
    finally:
        client_mod._pysnmp_hlapi = real_hlapi


def test_cmd_functions_raise_when_no_variant_found():
    """If neither camelCase nor snake_case exists, raise a clear ImportError.

    Defensive — catches a future pysnmp 8.x (or anything else) that
    renames these functions again. The error message mentions where to
    add a new variant.
    """
    import custom_components.hikvision_snmp.snmp_client as client_mod

    class EmptyHlapi:
        pass

    real_hlapi = client_mod._pysnmp_hlapi
    try:
        client_mod._pysnmp_hlapi = EmptyHlapi
        try:
            client_mod._resolve_cmd_functions()
        except ImportError as exc:
            assert "pysnmp" in str(exc)
            assert "_resolve_cmd_functions" in str(exc)
            return
        raise AssertionError("expected ImportError, got none")
    finally:
        client_mod._pysnmp_hlapi = real_hlapi


def test_module_does_not_eagerly_import_camelcase_cmd_names():
    """Regression guard for v0.1.14 — the module must not raise ImportError on pysnmp 7.x.

    This is the headline bug: before v0.1.14, ``snmp_client.py`` did
    ``from pysnmp.hlapi.asyncio import bulkCmd, getCmd, nextCmd`` which
    raises ``ImportError: cannot import name 'bulkCmd'`` on pysnmp 7.x
    — failing at module load time and surfacing as
    "无法加载配置向导: Invalid handler specified" in HA.
    """
    import custom_components.hikvision_snmp.snmp_client as client_mod
    # If module load had failed, this attribute wouldn't exist at all.
    assert hasattr(client_mod, "_resolve_cmd_functions")
    # And the resolved function names must match what the loaded pysnmp has.
    get, bulk, nxt = client_mod._resolve_cmd_functions()
    assert callable(get)
    assert callable(bulk)
    assert callable(nxt)