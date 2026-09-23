"""Async pysnmp v6 wrapper for Hikvision devices.

Uses ``pysnmp.hlapi.asyncio`` (PySNMP 6.x legacy API). PySNMP 7+ is
intentionally not supported by this integration to keep the dependency range
narrow and match the existing reference integration's tested baseline.
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
    bulkCmd,
    getCmd,
    nextCmd,
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
from pysnmp.proto.api import v2c as api_v2c
from pysnmp.proto.rfc1905 import NoSuchInstance, NoSuchObject

from .const import DEFAULT_PORT, DEFAULT_REQUEST_TIMEOUT, DEFAULT_RETRIES

_LOGGER = logging.getLogger(__name__)

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
    ) -> None:
        self._host = host
        self._port = port
        self._version = version
        self._auth = auth or {}
        self._engine = SnmpEngine()
        self._auth_data = _build_auth(version, self._auth)
        self._target = UdpTransportTarget(
            (host, port), timeout=DEFAULT_REQUEST_TIMEOUT, retries=DEFAULT_RETRIES
        )
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
        """Tear down the SNMP engine dispatcher."""
        # pysnmp 6.x uses camelCase; the method exists in all 6.x point releases.
        self._engine.closeDispatcher()

    # ---- internal ----

    async def _do_get_raw(self, var_binds_in):
        try:
            error_indication, error_status, _, var_binds = await getCmd(
                self._engine, self._auth_data, self._target, ContextData(), *var_binds_in
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