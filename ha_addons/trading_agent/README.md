# Trading Agent Add-on

One-shot Home Assistant OS add-on for the trading agent.

The add-on bundles the bot code in its container image, reads the operator configuration from `/share/trading-agent-data/operator_config.json`, writes outputs back to `/share/trading-agent-data`, and exits.