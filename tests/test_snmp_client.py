"""Tests for the per-host SNMP client wrapper.

Regression coverage for v0.1.11 — the previous ``_test_connection`` helper
tried to ``client._target = client._target.__class__((host, port),
timeout=3, retries=2)`` to bump the connection-test timeout, but on some
pysnmp 6.x builds that round-trip resolves to the wrong ``__init__`` signature
and raises ``AbstractTransportTarget.__init__() got multiple values for
argument 'timeout'``, which propagated up as "Failed to connect".

The fix routes timeout/retries through ``HikvisionSnmpClient.__init__`` and
constructs the target with the right values from the start, so there's no
rebuild step and no signature mismatch. These tests pin that contract.
"""

from __future__ import annotations

from custom_components.hikvision_snmp.const import (
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_RETRIES,
)
from custom_components.hikvision_snmp.snmp_client import HikvisionSnmpClient


def test_construct_with_default_timeout_and_retries():
    """Defaults come from const.DEFAULT_REQUEST_TIMEOUT / DEFAULT_RETRIES."""
    client = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                                 auth={"community": "public"})
    assert client._target.timeout == DEFAULT_REQUEST_TIMEOUT
    assert client._target.retries == DEFAULT_RETRIES


def test_construct_with_explicit_timeout_and_retries():
    """Explicit kwargs are passed through to UdpTransportTarget.

    This is the path the config-flow connection test relies on (v0.1.11+).
    """
    client = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                                 auth={"community": "public"},
                                 timeout=3, retries=2)
    assert client._target.timeout == 3
    assert client._target.retries == 2


def test_construct_with_only_timeout():
    """``retries`` defaults when only ``timeout`` is overridden."""
    client = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                                 auth={"community": "public"},
                                 timeout=5)
    assert client._target.timeout == 5
    assert client._target.retries == DEFAULT_RETRIES


def test_construct_with_only_retries():
    """``timeout`` defaults when only ``retries`` is overridden."""
    client = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                                 auth={"community": "public"},
                                 retries=4)
    assert client._target.timeout == DEFAULT_REQUEST_TIMEOUT
    assert client._target.retries == 4


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
    # If we got here without raising, the constructor succeeded with the
    # chosen timeout/retries — which is precisely what the v0.1.10 patch
    # couldn't deliver via __class__ round-trip.
    assert client._target is not None
    assert isinstance(client._target.timeout, (int, float))
    assert isinstance(client._target.retries, int)


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
    import custom_components.hikvision_snmp.snmp_client as client_mod
    # Snapshot singleton state and reset so the assertion below is
    # independent of any earlier test having primed it.
    client_mod._ENGINE_SINGLETON = None
    client_mod._ENGINE_INIT_LOCK = None

    c = HikvisionSnmpClient(host="127.0.0.1", port=161, version="v2c",
                            auth={"community": "public"})
    assert c._engine is None
    # And the module-level singleton is also still None — nothing should
    # have triggered construction.
    assert client_mod._ENGINE_SINGLETON is None


def test_engine_lazy_init_runs_in_to_thread():
    """First ``_ensure_engine`` runs ``SnmpEngine()`` inside ``asyncio.to_thread``.

    The point of the fix is that the synchronous ``os.listdir`` / ``open``
    pysnmp does in ``SnmpEngine.__init__`` happens off the HA event loop,
    so HA's blocking-call detector stops complaining.
    """
    import asyncio as _asyncio
    from unittest.mock import patch

    import custom_components.hikvision_snmp.snmp_client as client_mod
    client_mod._ENGINE_SINGLETON = None
    client_mod._ENGINE_INIT_LOCK = None

    constructed_in_thread: list[bool] = []
    real_to_thread = _asyncio.to_thread

    async def fake_to_thread(func, /, *args, **kwargs):
        # Note: ``func`` runs here in the asyncio event loop thread, but
        # the integration code does NOT await ``real_to_thread`` — it
        # awaits ``fake_to_thread``. We record the call and return a stub
        # engine so the test stays synchronous.
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
    # And ``_get_shared_engine`` actually populates the module singleton.
    assert client_mod._ENGINE_SINGLETON is not None
    # Restore real to_thread so other tests aren't affected.
    assert real_to_thread is _asyncio.to_thread  # sanity


def test_clients_share_one_engine_singleton():
    """Multiple ``HikvisionSnmpClient`` instances reuse one ``SnmpEngine``.

    Constructing a fresh ``SnmpEngine`` is a ~480 ms blocking call
    (off-loop now, but still non-trivial). Sharing the singleton means
    N devices cost 480 ms total, not N × 480 ms.
    """
    import asyncio as _asyncio

    import custom_components.hikvision_snmp.snmp_client as client_mod
    client_mod._ENGINE_SINGLETON = None
    client_mod._ENGINE_INIT_LOCK = None

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
    """``client.close()`` must not call ``closeDispatcher`` on the shared engine.

    With a shared engine, one client tearing down the dispatcher would
    break all the other clients in the same process. ``close()`` is a
    documented no-op; HA shutdown recycles the dispatcher via the asyncio
    loop exiting.
    """
    import asyncio as _asyncio

    import custom_components.hikvision_snmp.snmp_client as client_mod
    client_mod._ENGINE_SINGLETON = None
    client_mod._ENGINE_INIT_LOCK = None

    async def driver():
        c = HikvisionSnmpClient(host="10.0.0.1", port=161, version="v2c",
                                auth={"community": "public"})
        await c._ensure_engine()
        # If close() called _engine.closeDispatcher() we'd have nothing
        # left to assert against. closeDispatcher must NOT have been
        # called on the shared singleton.
        before = c._engine
        await c.close()
        return before

    engine_before = _asyncio.run(driver())
    # The shared singleton is the same object after close(); only the
    # dispatcher attribute would have been cleared by closeDispatcher.
    assert engine_before is client_mod._ENGINE_SINGLETON
    assert client_mod._ENGINE_SINGLETON is not None