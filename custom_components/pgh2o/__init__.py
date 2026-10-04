"""Pittsburgh Water (PGH2O) integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import PGH2OCoordinator

PLATFORMS = [Platform.SENSOR]

type PGH2OConfigEntry = ConfigEntry[PGH2OCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: PGH2OConfigEntry) -> bool:
    """Set up from a config entry."""
    coordinator = PGH2OCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PGH2OConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
