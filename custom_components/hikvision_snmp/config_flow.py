"""Config flow for Hikvision SNMP."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

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
    HIKVISION_PRIVATE_MIB_ROOT,
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
    """Return the per-version SNMP credential schema."""
    if version == "v2c":
        return vol.Schema({vol.Required(CONF_COMMUNITY): str})
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_AUTH_PROTOCOL, default="SHA"): vol.In(V3_AUTH_PROTOCOLS),
            vol.Required(CONF_AUTH_KEY): str,
            vol.Required(CONF_PRIVACY_PROTOCOL, default="AES128"): vol.In(V3_PRIVACY_PROTOCOLS),
            vol.Required(CONF_PRIVACY_KEY): str,
        }
    )


async def _test_connection(host: str, port: int, version: str, auth: dict) -> str | None:
    """Returns sysDescr string on success, None on failure."""
    client = HikvisionSnmpClient(host=host, port=port, version=version, auth=auth)
    try:
        sys_descr = await client.get(f"{HIKVISION_PRIVATE_MIB_ROOT}.1.1.1.1.0")
    except HikvisionSnmpError:
        await client.close()
        return None
    await client.close()
    if not sys_descr:
        return None
    return str(sys_descr)


class HikvisionSnmpConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hikvision SNMP."""

    VERSION = 1

    def __init__(self) -> None:
        self._basic: dict[str, Any] | None = None
        self._snmp: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="basic", data_schema=USER_DATA_SCHEMA_BASIC
            )
        self._basic = user_input
        return await self.async_step_snmp()

    async def async_step_snmp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._basic is not None
        if user_input is None:
            cred_schema = _snmp_data_schema("v2c")
            full = vol.Schema(
                {
                    vol.Required(CONF_VERSION, default="v2c"): vol.In(SNMP_VERSIONS),
                    **cred_schema.schema,
                }
            )
            return self.async_show_form(step_id="snmp", data_schema=full)

        version = user_input.get(CONF_VERSION, "v2c")
        try:
            validated = _snmp_data_schema(version)(user_input)
        except vol.Invalid:
            cred_schema = _snmp_data_schema(version)
            full = vol.Schema(
                {
                    vol.Required(CONF_VERSION, default=version): vol.In(SNMP_VERSIONS),
                    **cred_schema.schema,
                }
            )
            return self.async_show_form(
                step_id="snmp",
                data_schema=full,
                errors={"base": "invalid_snmp_version"},
            )
        self._snmp = validated
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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

        result = await _test_connection(host, port, version, auth)
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
            },
        )


class HikvisionSnmpOptionsFlow(OptionsFlow):
    """Handle options flow."""

    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="options_general",
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