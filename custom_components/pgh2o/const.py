"""Constants for the PGH2O integration."""

from datetime import timedelta

DOMAIN = "pgh2o"
UPDATE_INTERVAL = timedelta(hours=6)
# Hours the portal can still revise (late meter reads, gap fills).
REWRITE_WINDOW = timedelta(days=7)
