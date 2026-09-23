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