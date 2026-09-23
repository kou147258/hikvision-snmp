"""Config flow for Hikvision SNMP.

Uses the standard HA multi-step config flow pattern:
- step 1 (``step_id="user"``) — device basics (name, host, port, type)
- step 2 (``step_id="snmp"``) — SNMP credentials (v2c community or v3 user)
- step 3 (``step_id="confirm"``) — connection test + entry creation

Each step_id maps 1:1 to an ``async_step_<id>`` method on the
``HikvisionSnmpConfigFlow`` class — this is the pattern HA's flow manager
expects, and is what the standard config-flow template generates.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback

from .const import (
    CONF_AUTH_KEY,
    CONF_AUTH_PROTOCOL,
    CONF_COMMUNITY,
    CONF_DEVICE_TYPE,
    CONF_PRIVACY_KEY,
    CONF_PRIVACY_PROTOCOL,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    CONF_VERSION,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_TYPES,
    DOMAIN,
    HIKVISION_IPC_MIB_ROOT,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    SNMP_VERSIONS,
    V3_AUTH_PROTOCOLS,
    V3_PRIVACY_PROTOCOLS,
)
from .snmp_client import HikvisionSnmpClient, HikvisionSnmpError

USER_DATA_SCHEMA_BASIC = vol.Schema(
    {
        vol.Required(CONF_NAME, default="Hikvision NVR"): str,
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_DEVICE_TYPE, default="auto"): vol.In(DEVICE_TYPES),
    }
)


def _snmp_data_schema(version: str) -> vol.Schema:
    """Return the per-version SNMP credential schema.

    The returned schema includes ``CONF_VERSION`` itself so the same dict
    is used for both form display and form-submission validation
    (voluptuous rejects extra keys by default, so leaving ``CONF_VERSION``
    out of the validation schema would always fail).

    ``extra=vol.ALLOW_EXTRA`` is required because the form is rebuilt
    with only the per-version fields but HA's HTML form submission
    always carries all currently-rendered fields, including the v2c
    ``community`` field as an empty string when the user has selected
    v3 — without ``ALLOW_EXTRA`` that empty key trips ``vol.Invalid``.
    """
    base = {vol.Required(CONF_VERSION, default="v2c"): vol.In(SNMP_VERSIONS)}
    non_empty = vol.All(str, vol.Length(min=1))
    if version == "v2c":
        return vol.Schema(
            {**base, vol.Required(CONF_COMMUNITY): non_empty},
            extra=vol.ALLOW_EXTRA,
        )
    return vol.Schema(
        {
            **base,
            vol.Required(CONF_USERNAME): non_empty,
            vol.Required(CONF_AUTH_PROTOCOL, default="SHA"): vol.In(V3_AUTH_PROTOCOLS),
            vol.Required(CONF_AUTH_KEY): non_empty,
            vol.Required(CONF_PRIVACY_PROTOCOL, default="AES128"): vol.In(V3_PRIVACY_PROTOCOLS),
            vol.Required(CONF_PRIVACY_KEY): non_empty,
        },
        extra=vol.ALLOW_EXTRA,
    )


async def _test_connection(host: str, port: int, version: str, auth: dict) -> tuple[str | None, str]:
    """Returns ``(sysDescr, vendor)`` on success, ``(None, "")`` on any failure.

    Tries Hikvision IPC MIB (``.39165.1.1.0`` = model) first; if that fails,
    falls back to NVR MIB (``.50001.1.3.0`` = serial). Returns the resolved
    sysDescr string and the vendor identifier.

    Two non-obvious behaviours to defend against:

    1. **pysnmp first-request init overhead.** The first GET on a freshly
       constructed ``SnmpEngine`` triggers lazy init of message
       compilation + transport dispatcher — measurably slower than
       subsequent GETs (often 100-500 ms extra on a busy HA host). The
       default 1 s per-request timeout is tight against that, especially
       for Hikvision V5.x firmware which itself responds in 200-500 ms
       when idle. v0.1.9 uses an explicit 3 s / 2 retries budget for the
       connection test to absorb both the init overhead and a slow first
       device response.
    2. **Standard MIB-II probe before vendor MIB probe.** Hikvision devices
       always implement standard MIB-II (.1.3.6.1.2.1.*) but the *vendor
       MIB* (.1.3.6.1.4.1.39165 / .50001) is gated by a separate "Extended
       MIB" / "私有 MIB" toggle in the device's SNMP config that many
       admins leave off. A GET to sysUpTime also acts as a *warm-up*
       for pysnmp so the subsequent vendor-MIB GET doesn't pay the init
       cost.
    """
    from .const import (
        HIKVISION_NVR_MIB_ROOT,
        VENDOR_HIKVISION_IPC,
        VENDOR_HIKVISION_NVR,
    )

    try:
        # Build the client with a more lenient timeout/retries than the
        # coordinator's defaults so that the very first GET (which pays
        # pysnmp's lazy-init cost) and a slow Hikvision V5.x first response
        # don't trip the test. Passing them through the constructor rather
        # than rebuilding client._target via __class__() avoids the
        # ``AbstractTransportTarget.__init__() got multiple values for
        # argument 'timeout'`` error some pysnmp 6.x builds raise when
        # __class__() round-trip resolves to the wrong __init__ signature.
        client = HikvisionSnmpClient(
            host=host,
            port=port,
            version=version,
            auth=auth,
            timeout=3,
            retries=2,
        )
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("SNMP client construction failed for %s:%s: %s", host, port, exc)
        return None, ""

    try:
        # Warm-up: ping a standard MIB-II scalar that every SNMP agent
        # implements. Ignores the response; its only purpose is to flush
        # pysnmp lazy-init state so the vendor-MIB GET below runs at
        # steady-state speed.
        try:
            await client.get("1.3.6.1.2.1.1.3.0")  # sysUpTime
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("warm-up GET failed (ignored): %s", exc)

        # Try IPC root first
        for ipc_oid in (f"{HIKVISION_IPC_MIB_ROOT}.1.1.0", f"{HIKVISION_IPC_MIB_ROOT}.1.1.1.1.0"):
            try:
                val = await client.get(ipc_oid)
                if val:
                    return str(val), VENDOR_HIKVISION_IPC
            except HikvisionSnmpError:
                continue
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("IPC probe %s failed: %s", ipc_oid, exc)
                continue
        # Fall back to NVR root
        try:
            val = await client.get(f"{HIKVISION_NVR_MIB_ROOT}.1.3.0")
            if val:
                return str(val), VENDOR_HIKVISION_NVR
        except HikvisionSnmpError:
            pass
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("NVR probe failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Unexpected error in _test_connection(%s:%s): %s", host, port, exc)
        return None, ""
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass
    return None, ""


class HikvisionSnmpConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hikvision SNMP.

    Three-step flow: ``user`` → ``snmp`` → ``confirm``. Each step_id
    matches a method below 1:1 — this is the canonical HA pattern.
    """

    VERSION = 1

    def __init__(self) -> None:
        self._basic: dict[str, Any] | None = None
        self._snmp: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1 — device basics (name, host, port, type).

        This is both the entry point HA calls when the user clicks "Add
        Integration", AND the handler for the form's submit (because the
        form below uses ``step_id="user"``).
        """
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=USER_DATA_SCHEMA_BASIC
            )
        self._basic = user_input
        return await self.async_step_snmp()

    async def async_step_snmp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2 — SNMP credentials (v2c community or v3 user).

        The form is rebuilt with the matching per-version schema so that
        if the user picks v3 and submits with empty v2c fields, they see
        the v3 fields highlighted on the next render.
        """
        assert self._basic is not None
        if user_input is None:
            return self.async_show_form(
                step_id="snmp", data_schema=_snmp_data_schema("v2c")
            )

        version = user_input.get(CONF_VERSION, "v2c")
        try:
            validated = _snmp_data_schema(version)(user_input)
        except vol.Invalid:
            return self.async_show_form(
                step_id="snmp",
                data_schema=_snmp_data_schema(version),
                errors={"base": "invalid_snmp_version"},
            )
        self._snmp = validated
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3 — connection test + entry creation."""
        assert self._basic is not None and self._snmp is not None
        host = self._basic[CONF_HOST]
        port = self._basic.get(CONF_PORT, DEFAULT_PORT)
        version = self._snmp[CONF_VERSION]
        if version == "v2c":
            auth = {"community": self._snmp[CONF_COMMUNITY]}
        else:
            auth = {
                "username": self._snmp[CONF_USERNAME],
                "auth_protocol": self._snmp[CONF_AUTH_PROTOCOL],
                "auth_key": self._snmp[CONF_AUTH_KEY],
                "privacy_protocol": self._snmp[CONF_PRIVACY_PROTOCOL],
                "priv_key": self._snmp[CONF_PRIVACY_KEY],
            }

        await self.async_set_unique_id(f"{host}:{port}")
        self._abort_if_unique_id_configured()

        result, vendor = await _test_connection(host, port, version, auth)
        if not result:
            return self.async_show_form(
                step_id="confirm",
                errors={"base": "cannot_connect"},
                description_placeholders={"host": host},
            )

        return self.async_create_entry(
            title=self._basic.get(CONF_NAME, f"Hikvision {host}"),
            data={
                **self._basic,
                **self._snmp,
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                "vendor": vendor,
            },
        )


class HikvisionSnmpOptionsFlow(OptionsFlow):
    """Handle options flow."""

    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Options step — scan interval only.

        The standard HA OptionsFlow pattern uses ``async_step_init`` with
        ``step_id="init"``. (An earlier version of this code used
        ``step_id="options_general"`` which routed form submission to a
        non-existent method and produced the same
        ``Handler HikvisionSnmpOptionsFlow doesn't support step ...``
        error as the original config-flow bug.)
        """
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(
                        int, vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                    ),
                }
            ),
        )


@callback
def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
    return HikvisionSnmpOptionsFlow(entry)
