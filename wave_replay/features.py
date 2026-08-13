from __future__ import annotations

import numpy as np
import pandas as pd


def add_features(df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    out = df.copy()

    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    out["tr"] = tr
    out["atr"] = tr.rolling(atr_period, min_periods=max(5, atr_period // 2)).mean()

    out["return_5"] = out["close"].pct_change(5)
    out["return_20"] = out["close"].pct_change(20)

    # 使用“当前成交量 / 前20根平均成交量”，避免把当前量同时计入分母。
    prior_vol_mean = out["volume"].shift(1).rolling(20, min_periods=10).mean()
    out["volume_ratio_20"] = out["volume"] / prior_vol_mean.replace(0, np.nan)

    daily_range = (out["high"] - out["low"]).replace(0, np.nan)
    out["close_position_in_day"] = (out["close"] - out["low"]) / daily_range

    out["high_30"] = out["high"].rolling(30, min_periods=1).max()
    out["low_30"] = out["low"].rolling(30, min_periods=1).min()
    out["high_365"] = out["high"].rolling(365, min_periods=1).max()
    out["low_365"] = out["low"].rolling(365, min_periods=1).min()

    out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
    out["ema50"] = out["close"].ewm(span=50, adjust=False).mean()

    return out


def snapshot_features(df: pd.DataFrame) -> dict:
    x = df.iloc[-1]

    def f(name, default=None):
        v = x.get(name, default)
        if pd.isna(v):
            return default
        return float(v)

    return {
        "price": f("close"),
        "atr": f("atr"),
        "return_5": f("return_5"),
        "return_20": f("return_20"),
        "volume_ratio_20": f("volume_ratio_20"),
        "close_position_in_day": f("close_position_in_day"),
        "high_30": f("high_30"),
        "low_30": f("low_30"),
        "high_365": f("high_365"),
        "low_365": f("low_365"),
        "as_of": str(x["open_time"]),
    }
