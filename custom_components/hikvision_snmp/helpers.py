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