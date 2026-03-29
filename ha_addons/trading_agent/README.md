# Trading Agent Add-on

One-shot Home Assistant OS add-on for the trading agent.

The add-on bundles the bot code in its container image, reads the operator configuration from `/share/trading-agent-data/operator_config.json`, writes outputs back to `/share/trading-agent-data`, and exits.

The companion HA-side example files for this mode are now split by responsibility:
- `home_assistant_package_haos_addon.yaml.example` for helpers, sensors, and shell commands
- `home_assistant_scripts_haos_addon.yaml.example` for `/config/scripts.yaml`
- `home_assistant_automations_haos_addon.yaml.example` for `/config/automations.yaml`
- `home_assistant_dashboard_haos_addon.yaml.example` for the Lovelace dashboard
