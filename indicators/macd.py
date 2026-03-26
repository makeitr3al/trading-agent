import pandas as pd


def compute_macd(
    closes: pd.Series, fast_period: int, slow_period: int, signal_period: int
) -> pd.DataFrame:
    fast_ema = closes.ewm(span=fast_period, adjust=False).mean()
    slow_ema = closes.ewm(span=slow_period, adjust=False).mean()
    macd = fast_ema - slow_ema
    # We use the platform-common EMA signal line first; if needed, we can switch to SMA later.
    macd_signal = macd.ewm(span=signal_period, adjust=False).mean()

    return pd.DataFrame(
        {
            "macd": macd,
            "macd_signal": macd_signal,
        }
    )
