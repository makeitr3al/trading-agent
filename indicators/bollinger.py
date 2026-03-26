import pandas as pd


def compute_bollinger_bands(
    closes: pd.Series, period: int, std_dev: float
) -> pd.DataFrame:
    bb_middle = closes.rolling(window=period).mean()
    bb_std = closes.rolling(window=period).std()
    bb_upper = bb_middle + std_dev * bb_std
    bb_lower = bb_middle - std_dev * bb_std

    return pd.DataFrame(
        {
            "bb_middle": bb_middle,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
        }
    )
