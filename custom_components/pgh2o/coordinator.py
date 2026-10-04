"""Fetch PGH2O data and write it as long-term statistics."""

from __future__ import annotations

from datetime import timedelta
import logging

import aiohttp

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import VolumeConverter

from .api import HourlyData, InvalidAuth, PGH2OClient, PGH2OError, hourly_points
from .const import DOMAIN, REWRITE_WINDOW, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


def statistic_id(account: str) -> str:
    """Statistic ID for the Energy dashboard."""
    return f"{DOMAIN}:{account}_water_consumption"


class PGH2OCoordinator(DataUpdateCoordinator[HourlyData]):
    """Fetch hourly data every few hours."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=UPDATE_INTERVAL
        )
        self.client = PGH2OClient(
            async_create_clientsession(hass),
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
        )

    async def _async_update_data(self) -> HourlyData:
        try:
            data = await self.client.async_fetch_hourly()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (PGH2OError, aiohttp.ClientError) as err:
            raise UpdateFailed(str(err)) from err
        await self._async_import_statistics(data)
        return data

    async def _async_import_statistics(self, data: HourlyData) -> None:
        points = hourly_points(data)
        if not points:
            return
        stat_id = statistic_id(data.account)
        recorder = get_instance(self.hass)

        last = await recorder.async_add_executor_job(
            get_last_statistics, self.hass, 1, stat_id, True, {"sum"}
        )
        if not last.get(stat_id):
            base_sum = 0.0
            window = points
        else:
            last_start = dt_util.utc_from_timestamp(last[stat_id][0]["start"])
            # Write the recent days again: the portal fills gaps late.
            window_start = max(points[0][0], last_start - REWRITE_WINDOW)
            prev = await recorder.async_add_executor_job(
                statistics_during_period,
                self.hass,
                window_start - timedelta(hours=1),
                window_start,
                {stat_id},
                "hour",
                None,
                {"sum"},
            )
            prev_rows = prev.get(stat_id)
            if prev_rows and prev_rows[0].get("sum") is not None:
                base_sum = prev_rows[0]["sum"]
                window = [p for p in points if p[0] >= window_start]
            else:
                base_sum = last[stat_id][0]["sum"] or 0.0
                window = [p for p in points if p[0] > last_start]

        if not window:
            return
        total = base_sum
        stats: list[StatisticData] = []
        for start, gallons in window:
            total += gallons
            stats.append(StatisticData(start=start, state=gallons, sum=total))

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"PGH2O water {data.account}",
            source=DOMAIN,
            statistic_id=stat_id,
            unit_class=VolumeConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfVolume.GALLONS,
        )
        _LOGGER.debug("Writing %d hours to %s", len(stats), stat_id)
        async_add_external_statistics(self.hass, metadata, stats)
