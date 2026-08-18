from __future__ import annotations

from io import StringIO
from typing import Iterable
import time

import pandas as pd
import requests


BINANCE_BASES = (
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
)

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_buy_base",
    "taker_buy_quote", "ignore",
]

INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
}


def _request_klines(base: str, params: dict, timeout: int = 12) -> list:
    url = f"{base}/api/v3/klines"
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "code" in data:
        raise RuntimeError(f"Binance API error: {data}")
    return data


def fetch_binance_klines(
    symbol: str,
    interval: str = "1d",
    start: pd.Timestamp | str | None = None,
    end: pd.Timestamp | str | None = None,
    timezone: str = "8",
    max_bars: int = 2500,
) -> pd.DataFrame:
    """
    免费公共行情。无需 API Key。
    默认优先 data-api.binance.vision，失败后回退到 Binance 其它公开端点。
    """
    symbol = symbol.upper().strip()
    if interval not in INTERVAL_MS:
        raise ValueError(f"暂不支持 interval={interval}")

    if end is None:
        end_ts = pd.Timestamp.now(tz="UTC")
    else:
        end_ts = pd.Timestamp(end)
        if end_ts.tzinfo is None:
            end_ts = end_ts.tz_localize("Asia/Shanghai").tz_convert("UTC")
        else:
            end_ts = end_ts.tz_convert("UTC")

    if start is None:
        # 自动留足历史：最多 max_bars 根。
        start_ts = end_ts - pd.Timedelta(milliseconds=INTERVAL_MS[interval] * max_bars)
    else:
        start_ts = pd.Timestamp(start)
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize("Asia/Shanghai").tz_convert("UTC")
        else:
            start_ts = start_ts.tz_convert("UTC")

    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)

    rows: list[list] = []
    cursor = start_ms
    last_error = None

    while cursor <= end_ms and len(rows) < max_bars:
        limit = min(1000, max_bars - len(rows))
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms,
            "timeZone": timezone,
            "limit": limit,
        }

        batch = None
        for base in BINANCE_BASES:
            try:
                batch = _request_klines(base, params)
                break
            except Exception as exc:
                last_error = exc

        if batch is None:
            raise RuntimeError(f"所有 Binance 公共行情端点均失败：{last_error}")

        if not batch:
            break

        rows.extend(batch)
        last_open = int(batch[-1][0])
        next_cursor = last_open + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor

        if len(batch) < limit:
            break

        time.sleep(0.05)

    if not rows:
        raise RuntimeError(f"未获取到 {symbol} 的K线。请检查标的名称和时间范围。")

    df = pd.DataFrame(rows, columns=KLINE_COLUMNS)
    for col in ["open", "high", "low", "close", "volume", "quote_volume",
                "taker_buy_base", "taker_buy_quote"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trades"] = pd.to_numeric(df["trades"], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_convert("Asia/Shanghai")
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True).dt.tz_convert("Asia/Shanghai")
    df = df.drop_duplicates(subset=["open_time"]).sort_values("open_time").reset_index(drop=True)
    return validate_ohlcv(df)


def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    required = ["open_time", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"缺少必要字段：{missing}")

    out = df.copy()
    out["open_time"] = pd.to_datetime(out["open_time"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=required).sort_values("open_time").reset_index(drop=True)
    out = out[(out["high"] >= out[["open", "close", "low"]].max(axis=1)) &
              (out["low"] <= out[["open", "close", "high"]].min(axis=1))]
    if len(out) < 60:
        raise ValueError("有效K线少于60根，不足以做结构分析。")
    return out.reset_index(drop=True)


def load_csv_bytes(data: bytes) -> pd.DataFrame:
    text = data.decode("utf-8-sig", errors="replace")
    df = pd.read_csv(StringIO(text))

    aliases = {
        "date": "open_time", "datetime": "open_time", "time": "open_time",
        "timestamp": "open_time", "日期": "open_time", "时间": "open_time",
        "Open": "open", "High": "high", "Low": "low", "Close": "close",
        "Volume": "volume", "开盘": "open", "最高": "high", "最低": "low",
        "收盘": "close", "成交量": "volume",
    }
    df = df.rename(columns={c: aliases.get(c, c) for c in df.columns})

    if "open_time" not in df.columns and df.index.name:
        df = df.reset_index().rename(columns={df.index.name: "open_time"})

    return validate_ohlcv(df)


def resample_ohlcv(df: pd.DataFrame, rule: str = "1D") -> pd.DataFrame:
    """
    将更小周期K线聚合成更大周期K线。
    用于历史 WAVE 样本复现时避免“日K未来函数”：
    先抓到报告时刻为止的小时K，再聚合出当时可见的日K。
    """
    d = validate_ohlcv(df).copy()
    ts = pd.to_datetime(d["open_time"], errors="coerce")
    if getattr(ts.dt, "tz", None) is None:
        ts = ts.dt.tz_localize("Asia/Shanghai")
    else:
        ts = ts.dt.tz_convert("Asia/Shanghai")

    d = d.assign(open_time=ts).set_index("open_time")
    agg = d.resample(rule, label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    agg = agg.dropna(subset=["open", "high", "low", "close"]).reset_index()
    return validate_ohlcv(agg)
