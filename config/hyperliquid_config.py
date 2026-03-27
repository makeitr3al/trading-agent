from pydantic import BaseModel


class HyperliquidConfig(BaseModel):
    base_url: str = "https://api.hyperliquid.xyz"
    info_path: str = "/info"
    coin: str
    interval: str = "1h"
    lookback_bars: int = 200
