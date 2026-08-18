from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional

import pandas as pd

from .swings import SwingPoint
from .confluence import Zone


REFERENCE_BENCHMARKS = {
    "BTCUSDT": {
        "report_time": "2026-08-12 17:28:00+08:00",
        "basis_price": 63942.2,
        "anchors": [
            {"name": "大级别4浪起点", "kind": "node", "price": 116400.0, "date": "2025-11-14", "window_days": 20, "swing_kind": "H"},
            {"name": "4浪A终点", "kind": "node", "price": 60000.0, "date": "2026-06-02", "window_days": 20, "swing_kind": "L"},
            {"name": "4浪B终点", "kind": "node", "price": 66968.5, "date": "2026-07-22", "window_days": 12, "swing_kind": "H"},
            # WAVE原报告自身对C-1日期存在前后冲突，因此这里只按价格/类型，降低日期约束。
            {"name": "C-1低点", "kind": "node", "price": 61308.8, "date": None, "window_days": None, "swing_kind": "L"},
            {"name": "C-2高点", "kind": "node", "price": 65815.2, "date": "2026-07-24", "window_days": 12, "swing_kind": "H"},
            {"name": "C-3低点/C-4起点", "kind": "node", "price": 63529.8, "date": "2026-08-12", "window_days": 8, "swing_kind": "L"},
            {"name": "次级支撑", "kind": "node", "price": 62290.9, "date": "2026-08-03", "window_days": 12, "swing_kind": "L"},
            {"name": "C-4观察区", "kind": "zone", "low": 64400.0, "high": 65000.0, "side": "resistance"},
        ],
    },
    "ETHUSDT": {
        "report_time": "2026-08-11 15:28:00+08:00",
        "basis_price": 1871.68,
        "anchors": [
            {"name": "大级别高点", "kind": "node", "price": 4254.04, "date": "2025-10-27", "window_days": 25, "swing_kind": "H"},
            {"name": "中级别反弹起点", "kind": "node", "price": 1750.0, "date": "2026-07-13", "window_days": 12, "swing_kind": "L"},
            {"name": "中级别反弹高点", "kind": "node", "price": 1981.26, "date": "2026-07-26", "window_days": 14, "swing_kind": "H"},
            {"name": "小级别高点", "kind": "node", "price": 1943.60, "date": "2026-08-06", "window_days": 8, "swing_kind": "H"},
            {"name": "回调支撑区", "kind": "zone", "low": 1828.81, "high": 1848.63, "side": "support"},
            {"name": "365日低点", "kind": "node", "price": 1504.40, "date": "2025-06-05", "window_days": 35, "swing_kind": "L"},
        ],
    },
}


def _parse_time(x) -> pd.Timestamp:
    t = pd.Timestamp(x)
    if t.tzinfo is None:
        return t.tz_localize("Asia/Shanghai")
    return t.tz_convert("Asia/Shanghai")


def benchmark_cutoff(symbol: str) -> Optional[pd.Timestamp]:
    ref = REFERENCE_BENCHMARKS.get(symbol.upper())
    if not ref:
        return None
    return _parse_time(ref["report_time"])


def benchmark_basis(symbol: str) -> Optional[float]:
    ref = REFERENCE_BENCHMARKS.get(symbol.upper())
    return None if not ref else float(ref["basis_price"])


def _node_candidates(anchor: dict, swings: list[SwingPoint], used: set[int]) -> list[SwingPoint]:
    candidates = [p for p in swings if p.idx not in used]

    sk = anchor.get("swing_kind")
    if sk:
        candidates = [p for p in candidates if p.kind == sk]

    if anchor.get("date") and anchor.get("window_days"):
        center = _parse_time(anchor["date"])
        w = pd.Timedelta(days=int(anchor["window_days"]))
        timed = []
        for p in candidates:
            pt = _parse_time(p.time)
            if abs(pt - center) <= w:
                timed.append(p)
        # 时间窗内没有就判未命中，不再跨几个月找“价格最近点”冒充。
        candidates = timed

    return candidates


def _match_node(anchor: dict, swings: list[SwingPoint], used: set[int]) -> dict:
    target = float(anchor["price"])
    candidates = _node_candidates(anchor, swings, used)

    if not candidates:
        return {
            "WAVE项目": anchor["name"],
            "类型": "结构节点",
            "WAVE目标": target,
            "Replay结果": None,
            "误差%": None,
            "状态": "未在时间窗内命中",
        }

    # 价格误差 + 小幅时间惩罚，优先在正确时间附近找正确结构点。
    center = _parse_time(anchor["date"]) if anchor.get("date") else None

    def score(p: SwingPoint):
        pe = abs(p.price - target) / max(abs(target), 1e-12)
        te = 0.0
        if center is not None:
            te = abs((_parse_time(p.time) - center).total_seconds()) / 86400.0
            te = min(te / max(float(anchor.get("window_days") or 10), 1.0), 1.0)
        return pe + 0.05 * te

    best = min(candidates, key=score)
    used.add(best.idx)
    err_pct = abs(best.price - target) / abs(target) * 100 if target else None

    return {
        "WAVE项目": anchor["name"],
        "类型": "结构节点",
        "WAVE目标": target,
        "Replay结果": float(best.price),
        "误差%": float(err_pct),
        "状态": f"{best.kind}/{best.scale} · {str(best.time)[:10]}",
    }


def _zone_error(anchor: dict, z: Zone) -> float:
    al, ah = float(anchor["low"]), float(anchor["high"])
    zl, zh = float(z.low), float(z.high)
    ac = (al + ah) / 2.0
    zc = (zl + zh) / 2.0

    overlap = max(0.0, min(ah, zh) - max(al, zl))
    union = max(ah, zh) - min(al, zl)
    overlap_ratio = overlap / union if union > 0 else 0.0

    center_err = abs(zc - ac) / max(abs(ac), 1e-12) * 100
    # 有重叠则给予明显奖励；无重叠按中心误差评价。
    return max(center_err - overlap_ratio * 1.5, 0.0)


def _match_zone(anchor: dict, zones: list[Zone]) -> dict:
    candidates = zones
    side = anchor.get("side")
    if side:
        candidates = [z for z in candidates if z.side == side]

    if not candidates:
        return {
            "WAVE项目": anchor["name"],
            "类型": "共振区域",
            "WAVE目标": f"{anchor['low']:.4f}~{anchor['high']:.4f}",
            "Replay结果": None,
            "误差%": None,
            "状态": "未识别到同侧区域",
        }

    best = min(candidates, key=lambda z: _zone_error(anchor, z))
    err = _zone_error(anchor, best)
    return {
        "WAVE项目": anchor["name"],
        "类型": "共振区域",
        "WAVE目标": f"{anchor['low']:.4f}~{anchor['high']:.4f}",
        "Replay结果": f"{best.low:.4f}~{best.high:.4f}",
        "误差%": float(err),
        "状态": f"score={best.score:.2f}",
    }


def compare_to_reference(symbol: str, swings: list[SwingPoint], zones: list[Zone]) -> pd.DataFrame:
    ref = REFERENCE_BENCHMARKS.get(symbol.upper())
    if not ref:
        return pd.DataFrame()

    rows = []
    used: set[int] = set()

    for anchor in ref["anchors"]:
        if anchor["kind"] == "node":
            rows.append(_match_node(anchor, swings, used))
        elif anchor["kind"] == "zone":
            rows.append(_match_zone(anchor, zones))

    return pd.DataFrame(rows)


def benchmark_summary(symbol: str, current_price: float, result: pd.DataFrame) -> dict:
    ref = REFERENCE_BENCHMARKS.get(symbol.upper())
    if not ref:
        return {}

    basis = float(ref["basis_price"])
    basis_diff_pct = abs(float(current_price) - basis) / abs(basis) * 100 if basis else None
    valid_errors = result["误差%"].dropna() if not result.empty and "误差%" in result.columns else pd.Series(dtype=float)
    missed = int(result["误差%"].isna().sum()) if not result.empty else 0

    return {
        "wave_basis": basis,
        "basis_diff_pct": basis_diff_pct,
        "mean_error_pct": float(valid_errors.mean()) if len(valid_errors) else None,
        "median_error_pct": float(valid_errors.median()) if len(valid_errors) else None,
        "hit_count": int(len(valid_errors)),
        "miss_count": missed,
        "score_valid": basis_diff_pct is not None and basis_diff_pct <= 1.0,
    }
