"""Async pysnmp wrapper for Hikvision devices.

Works with pysnmp 6.x and pysnmp 7.x via runtime API dispatch:

- **pysnmp 6.x** (``UdpTransportTarget((host, port), timeout=N, retries=M)``,
  ``getCmd`` / ``bulkCmd`` / ``nextCmd``) — the legacy API the integration
  was originally written against.
- **pysnmp 7.x** (``await UdpTransportTarget.create((host, port), ...)``,
  ``get_cmd`` / ``bulk_cmd`` / ``next_cmd``) — HAOS 2026.x ships
  pysnmp 7.1.29 system-wide at
  ``/usr/local/lib/python3.14/site-packages/pysnmp/``, and the manifest
  pin ``pysnmp<8.0.0`` doesn't override that.

The two APIs differ at the request level (target constructor) AND at
the module-load level (cmd function names). Both dispatch points use
runtime introspection — see ``_detect_udp_target_api`` and
``_resolve_cmd_functions``.
"""

from __future__ import annotations

import logging
from typing import Any

from pysnmp.hlapi.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    usm3DESEDEPrivProtocol,
    usmAesCfb128Protocol,
    usmAesCfb192Protocol,
    usmAesCfb256Protocol,
    usmDESPrivProtocol,
    usmHMAC128SHA224AuthProtocol,
    usmHMAC192SHA256AuthProtocol,
    usmHMAC256SHA384AuthProtocol,
    usmHMAC384SHA512AuthProtocol,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
)
# IMPORTANT: do NOT use ``from pysnmp.hlapi.asyncio import getCmd, bulkCmd,
# nextCmd`` here — those names exist only in pysnmp 6.x. pysnmp 7.x renamed
# them to ``get_cmd``, ``bulk_cmd``, ``next_cmd``. Importing them positionally
# makes the module LOAD raise ImportError on pysnmp 7.x, which breaks HA's
# integration loader — config_flow becomes unreachable and HA surfaces
# "无法加载配置向导: Invalid handler specified" when the user tries to add
# the integration. Resolve at runtime via ``_resolve_cmd_functions`` below.
import pysnmp.hlapi.asyncio as _pysnmp_hlapi
from pysnmp.proto.api import v2c as api_v2c
from pysnmp.proto.rfc1905 import NoSuchInstance, NoSuchObject

from .const import DEFAULT_PORT, DEFAULT_REQUEST_TIMEOUT, DEFAULT_RETRIES


def _resolve_cmd_functions():
    """Resolve ``get`` / ``bulk`` / ``next`` cmd function names across pysnmp major versions.

    Returns ``(get_cmd, bulk_cmd, next_cmd)`` as a tuple of callables, using
    whichever naming convention the loaded pysnmp exposes:

    - pysnmp 6.x: camelCase — ``getCmd``, ``bulkCmd``, ``nextCmd``
    - pysnmp 7.x: snake_case — ``get_cmd``, ``bulk_cmd``, ``next_cmd``

    Tries camelCase first because that's the legacy convention the rest
    of this module uses internally (variables are named ``_do_get_raw``,
    ``_do_bulk``, ``_walk_next`` to match). Falls back to snake_case if
    any camelCase name is missing. Raises ImportError with an actionable
    message if neither variant is found (i.e. some future pysnmp 8.x
    renamed the API again — at that point, add a third branch here).
    """
    variants = (
        ("getCmd", "bulkCmd", "nextCmd"),     # pysnmp 6.x
        ("get_cmd", "bulk_cmd", "next_cmd"),  # pysnmp 7.x
    )
    for variant in variants:
        if all(hasattr(_pysnmp_hlapi, name) for name in variant):
            return tuple(getattr(_pysnmp_hlapi, name) for name in variant)
    raise ImportError(
        "Could not locate get/bulk/next cmd functions in pysnmp.hlapi.asyncio; "
        "tried camelCase (pysnmp 6.x) and snake_case (pysnmp 7.x). If a "
        "future pysnmp release renamed them again, add another variant to "
        "_resolve_cmd_functions()."
    )


getCmd, bulkCmd, nextCmd = _resolve_cmd_functions()

_LOGGER = logging.getLogger(__name__)

# ---- Shared SnmpEngine singleton ----
#
# pysnmp 6.x's ``SnmpEngine()`` constructor itself triggers synchronous
# ``os.listdir()`` / ``open()`` calls against the local MIB directory
# (``<pysnmp>/smi/mibs/``). On HAOS the integration runs inside the event
# loop, so HA's blocking-call detector flags each one as a violation:
#
#     Detected blocking call to listdir with args
#         ('/usr/local/lib/python3.14/site-packages/pysnmp/smi/mibs',)
#         inside the event loop by custom integration 'hikvision_snmp'
#         at .../snmp_client.py, line 100: self._engine = SnmpEngine()
#
# v0.1.9 added ``lookupMib=False`` to ``getCmd`` / ``bulkCmd`` / ``nextCmd``,
# but the blocking call comes from ``SnmpEngine.__init__`` itself (which
# immediately calls ``importSymbols("__SNMP-FRAMEWORK-MIB", ...)`` to seed
# engine state) — that's a constructor, not a request call, so
# ``lookupMib=False`` doesn't reach it.
#
# Fix: defer ``SnmpEngine()`` construction until the first request and
# run it inside ``asyncio.to_thread`` so the blocking FS calls happen
# off-loop. Share a single ``SnmpEngine`` across every
# ``HikvisionSnmpClient`` in this process — the 480 ms one-time cost
# shouldn't be paid per device, and pysnmp's per-call state (transport
# target, UsmUserData / CommunityData, request IDs) is keyed on the
# request arguments, not on engine state, so cross-client sharing is
# safe. The lazy init is gated by an ``asyncio.Lock`` to keep
# concurrent first-callers from racing on ``asyncio.to_thread``.
#
# ``SnmpEngine()`` does *not* bind to the asyncio event loop — the
# ``transportDispatcher`` attribute is left ``None`` and only lazy-created
# on the first ``getCmd`` / ``bulkCmd`` / ``nextCmd`` (which always run
# in the HA event loop), so it's safe to construct the engine inside a
# worker thread.

_ENGINE_SINGLETON: SnmpEngine | None = None
_ENGINE_INIT_LOCK: "asyncio.Lock | None" = None


async def _get_shared_engine() -> SnmpEngine:
    """Return the process-wide ``SnmpEngine``, constructing it on first use.

    Construction runs in ``asyncio.to_thread`` so the synchronous
    ``os.listdir`` / ``open`` calls pysnmp makes against its MIB
    directory don't block the HA event loop.
    """
    import asyncio as _asyncio

    global _ENGINE_SINGLETON, _ENGINE_INIT_LOCK
    if _ENGINE_SINGLETON is not None:
        return _ENGINE_SINGLETON
    if _ENGINE_INIT_LOCK is None:
        _ENGINE_INIT_LOCK = _asyncio.Lock()
    async with _ENGINE_INIT_LOCK:
        if _ENGINE_SINGLETON is None:
            _ENGINE_SINGLETON = await _asyncio.to_thread(SnmpEngine)
            _LOGGER.debug("pysnmp SnmpEngine singleton constructed")
    return _ENGINE_SINGLETON


# ---- Runtime pysnmp-API detection ----
#
# pysnmp 6.x (``UdpTransportTarget((host, port), timeout=N, retries=M)``) and
# pysnmp 7.x (``await UdpTransportTarget.create((host, port), timeout=N,
# retries=M)``) have completely incompatible ``__init__`` signatures for
# UdpTransportTarget. The v7 constructor takes only ``(timeout, retries,
# tagList)`` and refuses the positional address tuple, raising
# ``AbstractTransportTarget.__init__() got multiple values for argument
# 'timeout'`` if you pass it positionally.
#
# HAOS 2026.x ships with Python 3.14 and pulls pysnmp 7.x at the system
# level (``/usr/local/lib/python3.14/site-packages/pysnmp/``); the
# manifest pin ``pysnmp>=6.2.6,<7.0.0`` doesn't override that. So we have
# to detect at runtime and adapt.
#
# Detection: inspect ``UdpTransportTarget.__init__`` signature once per
# process. If ``transportAddr`` is a parameter, it's pysnmp 6.x. Otherwise
# it's pysnmp 7.x and we have to await ``UdpTransportTarget.create(...)``.


def _detect_udp_target_api() -> str:
    """Return ``"v6"`` or ``"v7"`` based on ``UdpTransportTarget.__init__``.

    Result is cached at module level because the inspection is cheap but
    we want the result to be consistent for the process lifetime.
    """
    import inspect as _inspect
    sig = _inspect.signature(UdpTransportTarget.__init__)
    if "transportAddr" in sig.parameters:
        return "v6"
    return "v7"


_UDP_TARGET_API: str | None = None


def _udp_target_api() -> str:
    """Cached wrapper around ``_detect_udp_target_api()``."""
    global _UDP_TARGET_API
    if _UDP_TARGET_API is None:
        _UDP_TARGET_API = _detect_udp_target_api()
    return _UDP_TARGET_API


async def _build_udp_target(host: str, port: int, timeout: float, retries: int):
    """Build a ``UdpTransportTarget`` against whatever pysnmp version is loaded.

    pysnmp 6.x is synchronous: ``UdpTransportTarget((host, port), ...)``.
    pysnmp 7.x is async: ``await UdpTransportTarget.create((host, port), ...)``.
    The 7.x signature doesn't even accept the address positionally — it
    raises ``AbstractTransportTarget.__init__() got multiple values for
    argument 'timeout'`` if you try, which is exactly the bug this
    function dodges.
    """
    api = _udp_target_api()
    if api == "v6":
        return UdpTransportTarget((host, port), timeout=timeout, retries=retries)
    # pysnmp 7.x
    return await UdpTransportTarget.create((host, port), timeout=timeout, retries=retries)


# ---- Protocol name → pysnmp protocol-object maps ----

_AUTH_PROTOCOLS = {
    "MD5": usmHMACMD5AuthProtocol,
    "SHA": usmHMACSHAAuthProtocol,
    "SHA224": usmHMAC128SHA224AuthProtocol,
    "SHA256": usmHMAC192SHA256AuthProtocol,
    "SHA384": usmHMAC256SHA384AuthProtocol,
    "SHA512": usmHMAC384SHA512AuthProtocol,
}

_PRIVACY_PROTOCOLS = {
    "DES": usmDESPrivProtocol,
    "3DES": usm3DESEDEPrivProtocol,
    "AES128": usmAesCfb128Protocol,
    "AES192": usmAesCfb192Protocol,
    "AES256": usmAesCfb256Protocol,
}


def _build_auth(version: str, auth: dict[str, str]):
    """Build pysnmp auth-data object from the dict stored in config entry."""
    if version == "v2c":
        return CommunityData(auth["community"], mpModel=1)
    if version == "v3":
        auth_proto = _AUTH_PROTOCOLS.get(auth.get("auth_protocol", "SHA"), usmHMACSHAAuthProtocol)
        priv_proto = _PRIVACY_PROTOCOLS.get(
            auth.get("privacy_protocol", "AES128"), usmAesCfb128Protocol
        )
        return UsmUserData(
            userName=auth["username"],
            authKey=auth["auth_key"],
            authProtocol=auth_proto,
            privKey=auth["priv_key"],
            privProtocol=priv_proto,
        )
    raise ValueError(f"Unsupported SNMP version: {version}")


class HikvisionSnmpError(Exception):
    """Raised when an SNMP request fails (timeout, decode error, etc.)."""


class HikvisionSnmpClient:
    """Per-host async SNMP client wrapping pysnmp 6.x."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        version: str = "v2c",
        auth: dict[str, str] | None = None,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> None:
        """Construct a per-host async SNMP client.

        ``timeout`` and ``retries`` are the per-request timeout (seconds) and
        retry count passed to :class:`UdpTransportTarget`. They default to the
        integration-wide ``DEFAULT_REQUEST_TIMEOUT`` / ``DEFAULT_RETRIES`` for
        the data-polling coordinator, but the config-flow connection test
        passes ``timeout=3, retries=2`` to absorb both pysnmp's first-request
        lazy-init overhead and a slow first response from Hikvision V5.x
        firmware.

        Passing them as constructor arguments (rather than rebuilding the
        transport target in-place, which a previous version of this code
        attempted via ``client._target.__class__((host, port), timeout=3, ...)``)
        avoids ``AbstractTransportTarget.__init__() got multiple values for
        argument 'timeout'`` errors that some pysnmp 6.x builds raise when the
        rebuilt target's MRO resolution picks the wrong ``__init__`` signature.
        """
        self._host = host
        self._port = port
        self._version = version
        self._auth = auth or {}
        self._resolved_timeout = (
            timeout if timeout is not None else DEFAULT_REQUEST_TIMEOUT
        )
        self._resolved_retries = (
            retries if retries is not None else DEFAULT_RETRIES
        )
        # ``SnmpEngine`` AND ``UdpTransportTarget`` are both lazy-initialised
        # in ``_ensure_engine`` on the first request. The engine build runs
        # in ``asyncio.to_thread`` to keep its blocking MIB-directory FS
        # scan off the HA event loop, and the target is built against
        # whatever pysnmp API the runtime has — pysnmp 6.x takes a sync
        # ``UdpTransportTarget((host, port), timeout=..., retries=...)``,
        # pysnmp 7.x takes ``await UdpTransportTarget.create((host, port),
        # timeout=..., retries=...)`` — both of which have to be detected at
        # runtime since the manifest pin ``pysnmp<7.0.0`` doesn't override
        # a system-level pysnmp 7.x on HAOS 2026.x. See module docstring
        # above for the full rationale.
        self._engine: SnmpEngine | None = None
        self._target: Any | None = None
        self._auth_data = _build_auth(version, self._auth)
        # Once GETBULK times out on this client, skip it forever after. Some
        # Hikvision V5.x PTZ firmwares don't implement GETBULK; we don't want
        # to spend 4-6s per walk retrying a known-broken op.
        self._bulk_disabled = False
        # Pause between GETNEXT iterations. Default 200ms helps busy V5.x IPCs
        # whose SNMP daemon is starved by video streaming. Set to 0 for fast
        # devices that don't need the breathing room.
        self._inter_request_delay: float = 0.2

    @property
    def host(self) -> str:
        return self._host

    async def get(self, oid: str) -> Any | None:
        """Single GET. Returns decoded python value or None if OID missing/timeout."""
        var_binds = await self._do_get([ObjectType(ObjectIdentity(oid))])
        if not var_binds:
            return None
        return _decode_value(_var_bind_value(var_binds[0]))

    async def get_with_retry(
        self, oid: str, retries: int = 1, backoff: float = 0.5
    ) -> Any | None:
        """GET with retry + backoff for busy / flaky devices.

        On Hikvision V5.x IPCs under load, GET requests get starved by video
        streaming. A 500ms pause + retry recovers many of these. ``retries`` is
        the number of additional attempts beyond the first; ``backoff`` is
        seconds between attempts. Returns None if all attempts fail.
        """
        import asyncio as _asyncio

        last_exc: HikvisionSnmpError | None = None
        for attempt in range(retries + 1):
            try:
                return await self.get(oid)
            except HikvisionSnmpError as exc:
                last_exc = exc
                if attempt < retries:
                    _LOGGER.debug(
                        "get_with_retry %s attempt %d failed: %s (sleep %.1fs)",
                        oid, attempt + 1, exc, backoff,
                    )
                    await _asyncio.sleep(backoff)
        _LOGGER.debug("get_with_retry %s exhausted: %s", oid, last_exc)
        return None

    async def get_raw(self, oid: str) -> tuple[Any, Any, Any]:
        """Diagnostic variant — returns (error_indication, error_status, var_binds).

        Useful for diagnosing auth failures (community mismatch surfaces as
        non-None error_indication) without raising an exception.
        """
        return await self._do_get_raw([ObjectType(ObjectIdentity(oid))])

    async def walk(self, oid_root: str, max_repetitions: int = 25,
              known_leaves: list[str] | None = None) -> list[tuple[str, Any]]:
        """GETBULK walk with GETNEXT fallback and single-GET completion.

        First tries GETBULK (fast). If that times out or returns no entries —
        which happens on some Hikvision V5.x firmware that doesn't implement
        GETBULK properly — falls back to GETNEXT (one OID per request, slower
        but universally supported). Once GETBULK fails once for this client,
        bulk is disabled permanently (some firmware is broken on GETBULK).

        If ``known_leaves`` is given, any leaf OIDs in that list that did NOT
        appear in the walk are patched by issuing a single GET for each. This
        compensates for transient GETNEXT packet drops (V5.x PTZ firmware
        occasionally loses GETNEXT responses mid-walk).

        Returns ``[(oid_str, value), ...]`` for OIDs lexicographically >= oid_root.
        """
        results: list[tuple[str, Any]] = []
        if not self._bulk_disabled:
            try:
                results = await self._walk_bulk(oid_root, max_repetitions)
                if results:
                    return results
            except HikvisionSnmpError as exc:
                self._bulk_disabled = True
                _LOGGER.debug(
                    "GETBULK walk failed (%s), disabling GETBULK for this client",
                    exc,
                )
        # GETNEXT walk
        next_results = await self._walk_next(oid_root)
        results.extend(next_results)

        # Single-GET fallback for known leaves the walk missed
        if known_leaves:
            walked_oids = {r[0] for r in results}
            for leaf in known_leaves:
                full_oid = f"{oid_root.rstrip('.')}.{leaf}.0"
                if full_oid not in walked_oids:
                    try:
                        val = await self.get_with_retry(full_oid, retries=1, backoff=0.5)
                        _LOGGER.debug(
                            "fallback GET %s -> %r (type=%s)",
                            full_oid, val, type(val).__name__,
                        )
                        if val is not None:
                            results.append((full_oid, val))
                    except HikvisionSnmpError as exc:
                        _LOGGER.debug("single GET fallback %s failed: %s", full_oid, exc)
        return results

    async def _walk_bulk(self, oid_root: str, max_repetitions: int) -> list[tuple[str, Any]]:
        results: list[tuple[str, Any]] = []
        current = ObjectIdentity(oid_root)
        while True:
            var_binds = await self._do_bulk(current, max_repetitions)
            if not var_binds:
                break
            stop = True
            # pysnmp 6.x bulkCmd returns 2-D var_binds: outer = rows, inner = ObjectTypes.
            # Each row is a list of ObjectType namedtuples. Flatten to one iterable
            # of ObjectType objects for this iteration.
            for vb in _iter_object_types(var_binds):
                oid_str, decoded = _decode_var_bind(vb)
                if oid_str is None:
                    continue
                if not oid_str.startswith(oid_root):
                    return results
                results.append((oid_str, decoded))
                current = ObjectIdentity(oid_str)
                stop = False
            if stop:
                break
        return results

    async def _walk_next(self, oid_root: str) -> list[tuple[str, Any]]:
        """GETNEXT walk — one OID per request. Universal fallback.

        On Hikvision V5.x IPCs under load, GETNEXT requests can be starved by
        video streaming. We retry once on RequestTimedOut before giving up on a
        leaf, and sleep ``inter_request_delay`` seconds between iterations to
        give the device's SNMP daemon breathing room. Default 200ms — enough for
        busy V5.x PTZ/IPCs to respond reliably, doubling walk time vs. no delay.
        """
        import asyncio as _asyncio

        await self._ensure_engine()
        results: list[tuple[str, Any]] = []
        current = ObjectIdentity(oid_root)
        iteration = 0
        while True:
            iteration += 1
            if iteration > 100:
                _LOGGER.debug("_walk_next iteration cap reached")
                break
            # Pause between iterations to give device time to process other tasks
            if iteration > 1 and self._inter_request_delay > 0:
                await _asyncio.sleep(self._inter_request_delay)
            var_binds: list = []
            for attempt in range(2):
                try:
                    error_indication, error_status, _, var_binds = await nextCmd(
                        self._engine,
                        self._auth_data,
                        self._target,
                        ContextData(),
                        ObjectType(current),
                        lexicographicMode=False,
                        lookupMib=False,
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 0:
                        _LOGGER.debug(
                            "_walk_next iter=%d attempt %d failed: %s (sleep 0.5s)",
                            iteration, attempt + 1, exc,
                        )
                        await _asyncio.sleep(0.5)
                        continue
                    raise HikvisionSnmpError(f"next failed: {exc}") from exc
            _LOGGER.debug(
                "_walk_next iter=%d err_ind=%r err_stat=%r n_binds=%d current=%s",
                iteration, error_indication, error_status, len(var_binds) if var_binds else 0, current,
            )
            if error_indication:
                break
            if error_status:
                raise HikvisionSnmpError(f"next status: {error_status.prettyPrint()}")
            if not var_binds:
                break
            first_object_type = next(iter(_iter_object_types(var_binds)), None)
            if first_object_type is None:
                break
            oid_str, value = _decode_var_bind(first_object_type)
            if oid_str is None:
                break
            _LOGGER.debug(
                "_walk_next iter=%d returned oid=%r value=%r root=%r starts_with=%s",
                iteration, oid_str, value, oid_root, oid_str.startswith(oid_root),
            )
            if isinstance(value, str) and "No more variables" in value:
                break
            if not oid_str.startswith(oid_root):
                break
            if results and results[-1][0] == oid_str:
                break
            results.append((oid_str, value))
            current = ObjectIdentity(oid_str)
        return results

    async def close(self) -> None:
        """No-op.

        Pre-v0.1.12 this called ``self._engine.closeDispatcher()`` to tear
        down the SNMP transport dispatcher, but v0.1.12 introduced a
        process-wide ``SnmpEngine`` singleton shared across every
        ``HikvisionSnmpClient`` instance — calling ``closeDispatcher`` on
        one client would tear down the dispatcher for all other clients in
        the same process. The integration now lets the asyncio loop
        recycle the dispatcher when HA shuts down, which is the only
        moment we'd actually want the dispatcher torn down anyway.
        """
        return None

    # ---- internal ----

    async def _ensure_engine(self) -> SnmpEngine:
        """Lazy-init the shared ``SnmpEngine`` AND this client's target on first use.

        The engine build runs in ``asyncio.to_thread`` so pysnmp's
        blocking ``os.listdir`` / ``open`` calls against its MIB
        directory don't trip HA's event-loop blocking-call monitor.

        The target build (also lazy) dispatches between the pysnmp 6.x
        and 7.x APIs based on a runtime signature check, because the
        manifest pin ``pysnmp<7.0.0`` doesn't override a system-level
        pysnmp 7.x on HAOS 2026.x and the two APIs have incompatible
        constructors. See ``_build_udp_target`` for the dispatch logic.

        Safe to call from every public async method — fast-paths when
        the singleton is already built. ``self._engine`` and
        ``self._target`` are also populated as a convenience so the
        rest of the class keeps its existing ``self._engine`` /
        ``self._target`` references.
        """
        if self._engine is None:
            self._engine = await _get_shared_engine()
        if self._target is None:
            self._target = await _build_udp_target(
                self._host,
                self._port,
                self._resolved_timeout,
                self._resolved_retries,
            )
        return self._engine

    async def _do_get_raw(self, var_binds_in):
        await self._ensure_engine()
        try:
            error_indication, error_status, _, var_binds = await getCmd(
                self._engine,
                self._auth_data,
                self._target,
                ContextData(),
                *var_binds_in,
                lookupMib=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise HikvisionSnmpError(f"get failed: {exc}") from exc
        return error_indication, error_status, [tuple(vb) for vb in var_binds]

    async def _do_get(self, var_binds_in) -> list:
        error_indication, error_status, var_binds = await self._do_get_raw(var_binds_in)
        if error_indication:
            raise HikvisionSnmpError(f"get indication: {error_indication}")
        if error_status:
            raise HikvisionSnmpError(f"get status: {error_status.prettyPrint()}")
        return var_binds

    async def _do_bulk(self, base_oid: ObjectIdentity, max_repetitions: int) -> list:
        await self._ensure_engine()
        try:
            error_indication, error_status, _, var_binds = await bulkCmd(
                self._engine,
                self._auth_data,
                self._target,
                ContextData(),
                0,  # non-repeaters
                max_repetitions,
                ObjectType(base_oid),
                lexicographicMode=False,
                lookupMib=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise HikvisionSnmpError(f"bulk failed: {exc}") from exc
        if error_indication:
            raise HikvisionSnmpError(f"bulk indication: {error_indication}")
        if error_status:
            raise HikvisionSnmpError(f"bulk status: {error_status.prettyPrint()}")
        return [tuple(vb) for vb in var_binds]


def decode_value(value: Any) -> Any:
    """Convert pysnmp value objects to plain python types.

    Public helper so diagnostic tools (e.g. tools/snmp_probe.py) can decode
    raw var_binds without re-implementing the type handling.
    """
    if isinstance(value, (NoSuchInstance, NoSuchObject)):
        return None
    if isinstance(value, (int, float, str, bytes, bool)) or value is None:
        return value
    try:
        return value.prettyPrint()
    except Exception:  # noqa: BLE001
        return str(value)


def _iter_object_types(var_binds: Any) -> Any:
    """Iterate ObjectType instances from a pysnmp 6.x var_binds response.

    ``getCmd`` returns ``[ObjectType, ...]`` (1-D).
    ``nextCmd`` / ``bulkCmd`` return ``[[ObjectType, ...], ...]`` (2-D: rows
    of columns). This helper yields each ObjectType regardless of shape.
    """
    if not var_binds:
        return
    first = var_binds[0]
    if isinstance(first, (list, tuple)):
        for row in var_binds:
            for item in row:
                yield item
    else:
        for item in var_binds:
            yield item


def _var_bind_value(vb: Any) -> Any:
    """Return the value half of an ObjectType (namedtuple-like).

    pysnmp's ObjectType namedtuple supports indexing: ``vb[0]`` is the OID,
    ``vb[1]`` is the value.
    """
    try:
        return vb[1]
    except (IndexError, TypeError):
        return None


def _decode_var_bind(vb: Any) -> tuple[str | None, Any]:
    """Decode an ObjectType into ``(oid_string, decoded_value)``."""
    try:
        oid_str = str(vb[0])
    except (IndexError, TypeError):
        return None, None
    try:
        return oid_str, decode_value(vb[1])
    except (IndexError, TypeError):
        return oid_str, None


# Backward-compatible private alias (used internally below).
_decode_value = decode_value