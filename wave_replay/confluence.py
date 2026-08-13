from __future__ import annotations

from dataclasses import dataclass, asdict
import math

import numpy as np
import pandas as pd

from .swings import SwingPoint


FIB_RETRACE = (0.382, 0.5, 0.618, 0.786)
FIB_EXT = (0.618, 1.0, 1.618, 2.0)


@dataclass
class Level:
    price: float
    source: str
    weight: float = 1.0


@dataclass
class Zone:
    low: float
    high: float
    center: float
    score: float
    side: str
    sources: list[str]

    def to_dict(self):
        return asdict(self)


def nice_step(price: float) -> float:
    if price <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(price))
    normalized = price / magnitude
    # 让 BTC/ETH/股票都能形成自然整数心理位。
    if normalized < 2:
        step = magnitude * 0.02
    elif normalized < 5:
        step = magnitude * 0.05
    else:
        step = magnitude * 0.10
    return max(step, 10 ** (math.floor(math.log10(price)) - 3))


def fib_levels(a: SwingPoint, b: SwingPoint) -> list[Level]:
    low = min(a.price, b.price)
    high = max(a.price, b.price)
    diff = high - low
    if diff <= 0:
        return []

    levels = []
    if a.price < b.price:  # 上升段，回撤向下
        for r in FIB_RETRACE:
            levels.append(Level(high - r * diff, f"fib_{r:.3f}:{a.price:.4g}->{b.price:.4g}", 1.4))
        for r in FIB_EXT:
            levels.append(Level(high + r * diff, f"fib_ext_{r:.3f}:{a.price:.4g}->{b.price:.4g}", 1.0))
    else:  # 下跌段，反弹向上
        for r in FIB_RETRACE:
            levels.append(Level(low + r * diff, f"fib_{r:.3f}:{a.price:.4g}->{b.price:.4g}", 1.4))
        for r in FIB_EXT:
            levels.append(Level(low - r * diff, f"fib_ext_{r:.3f}:{a.price:.4g}->{b.price:.4g}", 1.0))
    return levels


def volume_profile_levels(df: pd.DataFrame, bins: int = 36, top_n: int = 6) -> list[Level]:
    d = df.tail(min(len(df), 240)).copy()
    typical = (d["high"] + d["low"] + d["close"]) / 3.0
    lo, hi = float(typical.min()), float(typical.max())
    if hi <= lo:
        return []

    edges = np.linspace(lo, hi, bins + 1)
    bucket = np.digitize(typical.to_numpy(), edges) - 1
    bucket = np.clip(bucket, 0, bins - 1)

    vol = np.zeros(bins)
    for i, v in zip(bucket, d["volume"].to_numpy()):
        vol[i] += float(v)

    idxs = np.argsort(vol)[::-1][:top_n]
    out = []
    maxv = max(vol.max(), 1e-12)
    for i in idxs:
        center = (edges[i] + edges[i+1]) / 2
        out.append(Level(float(center), "volume_hvn", 1.0 + float(vol[i] / maxv)))
    return out


def collect_levels(df: pd.DataFrame, nodes: list[SwingPoint]) -> list[Level]:
    current = float(df.iloc[-1]["close"])
    levels: list[Level] = []

    # 结构节点本身
    for p in nodes:
        w = {"short": 1.0, "medium": 1.5, "long": 2.2}.get(p.scale, 1.0)
        levels.append(Level(p.price, f"swing_{p.kind}_{p.scale}", w))

    # 最近若干条结构腿的Fibonacci
    recent = nodes[-8:]
    for a, b in zip(recent[:-1], recent[1:]):
        if a.kind != b.kind:
            levels.extend(fib_levels(a, b))

    # 30/365日极值
    for horizon in (30, min(365, len(df))):
        d = df.tail(horizon)
        levels.append(Level(float(d["high"].max()), f"{horizon}bar_high", 2.0))
        levels.append(Level(float(d["low"].min()), f"{horizon}bar_low", 2.0))

    # 心理整数位
    step = nice_step(current)
    start = math.floor(current * 0.75 / step) * step
    end = math.ceil(current * 1.25 / step) * step
    x = start
    while x <= end + 1e-9:
        levels.append(Level(float(x), "psychological_round", 0.65))
        x += step

    # 近240根成交密集区
    levels.extend(volume_profile_levels(df))
    return levels


def cluster_zones(
    df: pd.DataFrame,
    levels: list[Level],
    tolerance_pct: float = 0.007,
    atr_fraction: float = 0.45,
) -> list[Zone]:
    if not levels:
        return []

    current = float(df.iloc[-1]["close"])
    atr = float(df.iloc[-1]["atr"]) if "atr" in df.columns and pd.notna(df.iloc[-1]["atr"]) else 0.0
    tol = max(current * tolerance_pct, atr * atr_fraction, current * 0.0015)

    levels = sorted(levels, key=lambda x: x.price)
    clusters: list[list[Level]] = []

    for lv in levels:
        if not clusters:
            clusters.append([lv])
            continue
        last = clusters[-1]
        center = sum(x.price * x.weight for x in last) / sum(x.weight for x in last)
        if abs(lv.price - center) <= tol:
            last.append(lv)
        else:
            clusters.append([lv])

    zones = []
    for c in clusters:
        unique_sources = sorted(set(x.source for x in c))
        total_w = sum(x.weight for x in c)
        center = sum(x.price * x.weight for x in c) / total_w
        low, high = min(x.price for x in c), max(x.price for x in c)
        score = total_w + 0.65 * len(unique_sources)

        if high < current:
            side = "support"
        elif low > current:
            side = "resistance"
        else:
            side = "current"

        zones.append(Zone(
            low=float(low), high=float(high), center=float(center),
            score=float(score), side=side, sources=unique_sources,
        ))

    return sorted(zones, key=lambda z: z.score, reverse=True)


def zones_to_frame(zones: list[Zone], top_n: int = 12) -> pd.DataFrame:
    rows = []
    for z in zones[:top_n]:
        d = z.to_dict()
        d["sources"] = " | ".join(d["sources"])
        rows.append(d)
    return pd.DataFrame(rows)
