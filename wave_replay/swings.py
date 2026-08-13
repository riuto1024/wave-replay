from __future__ import annotations

from dataclasses import dataclass, asdict
import math
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass
class SwingPoint:
    idx: int
    time: pd.Timestamp
    kind: str       # "H" / "L"
    price: float
    score: float
    prominence: float
    atr_multiple: float
    max_window: int
    confirmations: int
    scale: str      # short / medium / long
    forced_reason: str = ""

    def to_dict(self):
        d = asdict(self)
        d["time"] = str(self.time)
        return d


def _scale(max_window: int, score: float) -> str:
    if max_window >= 13 or score >= 8.0:
        return "long"
    if max_window >= 5 or score >= 4.0:
        return "medium"
    return "short"


def _candidate_score(
    df: pd.DataFrame,
    idx: int,
    kind: str,
    window: int,
    min_pct: float,
    atr_mult: float,
) -> tuple[float, float, float] | None:
    if idx - window < 0 or idx + window >= len(df):
        return None

    price = float(df.at[idx, "high" if kind == "H" else "low"])
    atr = float(df.at[idx, "atr"]) if pd.notna(df.at[idx, "atr"]) else np.nan

    if kind == "H":
        left_ref = float(df.loc[idx-window:idx-1, "low"].min())
        right_ref = float(df.loc[idx+1:idx+window, "low"].min())
        prominence = min(price - left_ref, price - right_ref)
    else:
        left_ref = float(df.loc[idx-window:idx-1, "high"].max())
        right_ref = float(df.loc[idx+1:idx+window, "high"].max())
        prominence = min(left_ref - price, right_ref - price)

    if prominence <= 0:
        return None

    pct = prominence / max(abs(price), 1e-12)
    atr_multiple = prominence / atr if atr and atr > 0 and not math.isnan(atr) else 0.0

    if pct < min_pct and atr_multiple < atr_mult:
        return None

    vol = float(df.at[idx, "volume"])
    vol_avg = float(df["volume"].iloc[max(0, idx-20):idx].mean()) if idx > 0 else vol
    vol_bonus = min(max(vol / vol_avg - 1.0, 0.0), 2.0) if vol_avg > 0 else 0.0

    score = (
        1.50 * min(atr_multiple, 5.0)
        + 15.0 * min(pct, 0.20)
        + 0.45 * math.log1p(window)
        + 0.35 * vol_bonus
    )
    return score, prominence, atr_multiple


def _force_extrema(df: pd.DataFrame, points: dict[tuple[int, str], SwingPoint]) -> None:
    n = len(df)
    horizons = [
        (30, "30d_extreme", 6.5),
        (min(365, n), "365d_extreme", 8.5),
    ]
    for horizon, reason, bonus in horizons:
        sub = df.iloc[-horizon:]
        for kind, col, fn in [("H", "high", "idxmax"), ("L", "low", "idxmin")]:
            idx = int(getattr(sub[col], fn)())
            price = float(df.at[idx, col])
            atr = float(df.at[idx, "atr"]) if pd.notna(df.at[idx, "atr"]) else np.nan
            key = (idx, kind)
            if key in points:
                p = points[key]
                p.score = max(p.score, bonus)
                p.forced_reason = (p.forced_reason + "," + reason).strip(",")
                p.max_window = max(p.max_window, 21)
                p.scale = "long"
            else:
                points[key] = SwingPoint(
                    idx=idx,
                    time=df.at[idx, "open_time"],
                    kind=kind,
                    price=price,
                    score=bonus,
                    prominence=0.0,
                    atr_multiple=0.0 if pd.isna(atr) else 0.0,
                    max_window=21,
                    confirmations=1,
                    scale="long",
                    forced_reason=reason,
                )


def _compress_same_kind(points: list[SwingPoint]) -> list[SwingPoint]:
    if not points:
        return []
    out = [points[0]]
    for p in points[1:]:
        last = out[-1]
        if p.kind != last.kind:
            out.append(p)
            continue

        # 连续同类极值只保留“结构更强”的一个。
        better = p
        if last.score > p.score:
            better = last
        elif abs(last.score - p.score) < 0.5:
            if p.kind == "H":
                better = p if p.price >= last.price else last
            else:
                better = p if p.price <= last.price else last
        out[-1] = better
    return out


def detect_swings(
    df: pd.DataFrame,
    windows: Iterable[int] = (2, 3, 5, 8, 13, 21),
    min_pct: float = 0.012,
    atr_mult: float = 0.75,
) -> list[SwingPoint]:
    """
    多尺度 confirmed swing detector。
    目标不是普通“画分型”，而是为 WAVE 行为复现提供候选结构节点。
    """
    points: dict[tuple[int, str], SwingPoint] = {}
    highs = df["high"]
    lows = df["low"]

    for w in sorted(set(int(x) for x in windows if int(x) >= 1)):
        size = 2 * w + 1
        roll_high = highs.rolling(size, center=True).max()
        roll_low = lows.rolling(size, center=True).min()

        high_idx = np.flatnonzero((highs == roll_high).fillna(False).to_numpy())
        low_idx = np.flatnonzero((lows == roll_low).fillna(False).to_numpy())

        for kind, idxs in [("H", high_idx), ("L", low_idx)]:
            for idx in idxs:
                scored = _candidate_score(df, int(idx), kind, w, min_pct, atr_mult)
                if scored is None:
                    continue
                score, prominence, atr_multiple = scored
                key = (int(idx), kind)

                if key not in points:
                    points[key] = SwingPoint(
                        idx=int(idx),
                        time=df.at[int(idx), "open_time"],
                        kind=kind,
                        price=float(df.at[int(idx), "high" if kind == "H" else "low"]),
                        score=float(score),
                        prominence=float(prominence),
                        atr_multiple=float(atr_multiple),
                        max_window=w,
                        confirmations=1,
                        scale=_scale(w, score),
                    )
                else:
                    p = points[key]
                    p.score += 0.75 + 0.08 * w
                    p.prominence = max(p.prominence, float(prominence))
                    p.atr_multiple = max(p.atr_multiple, float(atr_multiple))
                    p.max_window = max(p.max_window, w)
                    p.confirmations += 1
                    p.scale = _scale(p.max_window, p.score)

    _force_extrema(df, points)

    ordered = sorted(points.values(), key=lambda p: (p.idx, 0 if p.kind == "L" else 1))
    ordered = _compress_same_kind(ordered)

    # 再去掉非常弱且只被单窗口发现的短周期噪音。
    filtered = [
        p for p in ordered
        if p.scale != "short" or p.confirmations >= 2 or p.score >= 3.0
    ]
    return filtered


def swings_to_frame(swings: list[SwingPoint]) -> pd.DataFrame:
    if not swings:
        return pd.DataFrame(columns=[
            "idx", "time", "kind", "price", "scale", "score",
            "prominence", "atr_multiple", "max_window", "confirmations", "forced_reason"
        ])
    return pd.DataFrame([p.to_dict() for p in swings])


def structural_nodes(swings: list[SwingPoint], max_nodes: int = 18) -> list[SwingPoint]:
    """
    兼顾时间连续性和结构强度：先选中/长级别，再补最强短级别。
    """
    if not swings:
        return []

    core = [p for p in swings if p.scale in ("medium", "long")]
    if len(core) < max_nodes:
        extras = sorted(
            [p for p in swings if p not in core],
            key=lambda x: x.score,
            reverse=True,
        )[: max_nodes - len(core)]
        core += extras

    # 若过多，按得分截断，但最终按时间排列。
    if len(core) > max_nodes:
        core = sorted(core, key=lambda x: x.score, reverse=True)[:max_nodes]

    core = sorted(core, key=lambda x: x.idx)
    return _compress_same_kind(core)
