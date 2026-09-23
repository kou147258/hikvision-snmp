"""Pure helpers for decoding SNMP responses."""

from __future__ import annotations

from datetime import timedelta
from typing import Any


def decode_octet_string(value: Any) -> str:
    """Decode OctetString from pysnmp into a clean string.

    Handles bytes, str, and None without raising.
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").replace("\x00", "").strip()
    if isinstance(value, str):
        return value.replace("\x00", "").strip()
    return str(value)


def parse_uptime(value: Any) -> timedelta:
    """Parse SNMP TimeTicks (1/100 s) into a timedelta."""
    if value is None:
        return timedelta(0)
    try:
        return timedelta(seconds=int(value) / 100)
    except (TypeError, ValueError):
        return timedelta(0)


def parse_int(value: Any) -> int | None:
    """Best-effort integer conversion; None on failure or None input."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_bool(value: Any) -> bool | None:
    """Map 1/0 to True/False; return None for unknown or None."""
    if value is None:
        return None
    parsed = parse_int(value)
    if parsed in (0, 1):
        return bool(parsed)
    return None


def parse_value_with_unit(value: Any) -> tuple[float | None, str | None]:
    """Parse Hikvision V5.x STRING values like ``"27 PERCENT"`` / ``"116.5 GB"``.

    Returns ``(numeric_value, unit)`` where ``unit`` is the trailing non-numeric
    token (e.g. ``"PERCENT"``, ``"GB"``) or None for unitless numerics. Returns
    ``(None, None)`` on missing / unparseable input.

    Examples:
        parse_value_with_unit("27 PERCENT")  -> (27.0, "PERCENT")
        parse_value_with_unit("116.5 GB")    -> (116.5, "GB")
        parse_value_with_unit("H.264")       -> (None, "H.264")
        parse_value_with_unit(27)            -> (27.0, None)
        parse_value_with_unit(None)          -> (None, None)
    """
    if value is None:
        return None, None
    if isinstance(value, bool):
        return float(value), None
    if isinstance(value, (int, float)):
        return float(value), None
    s = decode_octet_string(value)
    if not s:
        return None, None
    parts = s.split(maxsplit=1)
    if len(parts) == 2:
        try:
            return float(parts[0]), parts[1]
        except ValueError:
            return None, s
    try:
        return float(s), None
    except ValueError:
        return None, s


def decode_walk_results(
    raw: list[tuple[str, Any]],
    oid_root: str,
    oid_map: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Group GETBULK results by metric key.

    Each raw tuple is ``(oid_string, value)``. OIDs not under ``oid_root`` are
    dropped. For each remaining OID, the leading components are matched
    against ``oid_map`` values (each value is a multi-component prefix like
    ``"1.1"``); the trailing components are the instance index (e.g.
    ``"0"`` for scalars, ``"1"`` / ``"2"`` for table rows).

    Returns: ``{metric_key: {instance_str: value}}``.
    """
    root_parts = oid_root.split(".")
    out: dict[str, dict[str, Any]] = {}

    # Precompute leaf prefixes as parsed tuples for fast comparison
    parsed_map: list[tuple[str, list[str]]] = [
        (key, prefix.split(".")) for key, prefix in oid_map.items()
    ]

    for oid_str, value in raw:
        parts = oid_str.split(".")
        if parts[: len(root_parts)] != root_parts:
            continue
        rest = parts[len(root_parts):]
        if not rest:
            continue
        matched_key = None
        matched_instance: str | None = None
        for metric_key, leaf_parts in parsed_map:
            leaf_len = len(leaf_parts)
            if len(rest) < leaf_len:
                continue
            if rest[:leaf_len] == leaf_parts:
                matched_key = metric_key
                matched_instance = ".".join(rest[leaf_len:])
                break
        if matched_key is None:
            continue
        out.setdefault(matched_key, {})[matched_instance] = value

    return out