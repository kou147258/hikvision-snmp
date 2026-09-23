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

    @property
    def host(self) -> str:
        return self._host

    async def get(self, oid: str) -> Any | None:
        """Single GET. Returns decoded python value or None if OID missing/timeout."""
        var_binds = await self._do_get([ObjectType(ObjectIdentity(oid))])
        if not var_binds:
            return None
        return _decode_value(var_binds[0][1])

    async def get_raw(self, oid: str) -> tuple[Any, Any, Any]:
        """Diagnostic variant — returns (error_indication, error_status, var_binds).

        Useful for diagnosing auth failures (community mismatch surfaces as
        non-None error_indication) without raising an exception.
        """
        return await self._do_get_raw([ObjectType(ObjectIdentity(oid))])

    async def walk(self, oid_root: str, max_repetitions: int = 25) -> list[tuple[str, Any]]:
        """GETBULK walk. Returns ``[(oid_str, value), ...]`` for OIDs under oid_root."""
        results: list[tuple[str, Any]] = []
        current = ObjectIdentity(oid_root)
        ctx = ContextData()
        while True:
            var_binds = await self._do_bulk(current, max_repetitions)
            if not var_binds:
                break
            stop = True
            for var_bind in var_binds:
                oid_str = str(var_bind[0])
                value = _decode_value(var_bind[1])
                if not oid_str.startswith(oid_root):
                    return results
                results.append((oid_str, value))
                current = ObjectIdentity(oid_str)
                stop = False
            if stop:
                break
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


def _decode_value(value: Any) -> Any:
    """Convert pysnmp value objects to plain python types."""
    if isinstance(value, (NoSuchInstance, NoSuchObject)):
        return None
    if isinstance(value, (int, float, str, bytes, bool)) or value is None:
        return value
    try:
        return value.prettyPrint()
    except Exception:  # noqa: BLE001
        return str(value)