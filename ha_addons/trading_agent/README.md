# Trading Agent Add-on

One-shot Home Assistant OS add-on for the trading agent.

The add-on bundles the bot code in its container image, reads the operator configuration from `/share/trading-agent-data/operator_config.json`, writes outputs back to `/share/trading-agent-data`, and exits.

The companion file `home_assistant_package_haos_addon.yaml.example` now contains the full HA-side setup for this mode:
- helpers
- sensors
- shell commands
- scripts
- the daily scheduling automation
