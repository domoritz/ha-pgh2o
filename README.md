# Pittsburgh Water (PGH2O) for Home Assistant

A custom integration that imports hourly water use from the
[PGH2O Customer Advantage Portal](https://myaccount.pgh2o.com) into Home Assistant.
You can then show your water use in the Energy dashboard.

> [!WARNING]
> PGH2O has no public API. This integration uses the same requests as the portal web page.
> A change to the portal can stop the integration. The integration is not made or
> supported by Pittsburgh Water.

## How it works

- The integration logs in to the portal every 6 hours and gets the hourly use in gallons.
- The portal data is late by approximately one day. Thus the integration writes the
  values as long-term statistics at the correct hour, and not as a sensor state.
- The integration writes the last 7 days again on each update, because the portal fills
  gaps late.
- Meters that report only in 1000-gallon steps give 1000-gallon spikes. The integration
  starts at the first reading with finer resolution and does not import the older data.

## Installation

This integration requires [HACS](https://hacs.xyz).

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=domoritz&repository=ha-pgh2o&category=integration)

Then:

1. Select **Download** to install the integration.
2. Restart Home Assistant.

The integration icon shows in Home Assistant 2026.3 and later.

<details>
<summary>Add the repository manually</summary>

1. In HACS, open the menu (⋮) and select **Custom repositories**.
2. Add `https://github.com/domoritz/ha-pgh2o` with the type **Integration**.
3. Install **Pittsburgh Water (PGH2O)** and restart Home Assistant.

</details>

<details>
<summary>Install without HACS</summary>

Copy `custom_components/pgh2o` to `config/custom_components/` and restart Home Assistant.

</details>

## Configuration

[![Open your Home Assistant instance and start setting up the integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=pgh2o)

1. Select the button above, or go to **Settings → Devices & services → Add integration**
   and select **Pittsburgh Water (PGH2O)**.
2. Enter the username and password of your portal account.
3. Go to **Settings → Dashboards → Energy → Water consumption** and add the statistic
   **PGH2O water <account number>**.

Accounts with multi-factor verification are not supported.

## Entities

| Entity | Description |
| --- | --- |
| Statistic `pgh2o:<account>_water_consumption` | Hourly gallons, for the Energy dashboard |
| Data through | End of the last hour with final data |
| Usage in last 24 h of data | Gallons in the last 24 hours that the portal reported |

## Time offset

The portal labels have 24 hours on each day, also on the days when daylight saving time
starts or stops. The integration reads the labels as UTC−4 (`LABEL_TZ` in `api.py`).
If your use shows one hour late or early, open an issue.

## Test without Home Assistant

```sh
pip install aiohttp
cd custom_components/pgh2o
PGH2O_USER=... PGH2O_PASS=... python3 api.py
```

## Debug logs

```yaml
logger:
  logs:
    custom_components.pgh2o: debug
```
