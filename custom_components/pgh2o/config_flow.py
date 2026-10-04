"""Config flow for PGH2O."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import InvalidAuth, PGH2OClient, PGH2OError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class PGH2OConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the portal login."""

    VERSION = 1

    async def _async_validate(
        self, username: str, password: str, errors: dict[str, str]
    ) -> str | None:
        """Log in and return the account number, or set an error."""
        client = PGH2OClient(async_create_clientsession(self.hass), username, password)
        try:
            data = await client.async_fetch_hourly()
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except (PGH2OError, aiohttp.ClientError):
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error")
            errors["base"] = "unknown"
        else:
            return data.account
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the first setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            account = await self._async_validate(
                user_input[CONF_USERNAME], user_input[CONF_PASSWORD], errors
            )
            if account:
                await self.async_set_unique_id(account)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f"PGH2O {account}", data=user_input)
        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after the portal refused the login."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            account = await self._async_validate(
                entry.data[CONF_USERNAME], user_input[CONF_PASSWORD], errors
            )
            if account:
                await self.async_set_unique_id(account)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"username": entry.data[CONF_USERNAME]},
        )
