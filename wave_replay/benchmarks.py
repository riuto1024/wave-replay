from __future__ import annotations

import pandas as pd

from .swings import SwingPoint


REFERENCE_BENCHMARKS = {
    "BTCUSDT": {
        "report_time": "2026-08-12 17:28 Asia/Shanghai",
        "basis_price": 63942.2,
        "anchors": {
            "大级别4浪起点": 116400.0,
            "4浪A终点": 60000.0,
            "4浪B终点": 66968.5,
            "C-1低点": 61308.8,
            "C-2高点": 65815.2,
            "C-3低点/C-4起点": 63529.8,
            "次级支撑": 62290.9,
        },
    },
    "ETHUSDT": {
        "report_time": "2026-08-11 15:28 Asia/Shanghai",
        "basis_price": 1871.68,
        "anchors": {
            "大级别高点": 4254.04,
            "中级别反弹起点": 1750.0,
            "中级别反弹高点": 1981.26,
            "小级别高点": 1943.60,
            "回调支撑下沿": 1828.81,
            "回调支撑上沿": 1848.63,
            "365日低点": 1504.40,
        },
    },
}


def compare_to_reference(symbol: str, swings: list[SwingPoint]) -> pd.DataFrame:
    ref = REFERENCE_BENCHMARKS.get(symbol.upper())
    if not ref:
        return pd.DataFrame()

    detected = [p.price for p in swings]
    rows = []
    for name, price in ref["anchors"].items():
        if detected:
            nearest = min(detected, key=lambda x: abs(x - price))
            err_abs = nearest - price
            err_pct = abs(err_abs) / abs(price) * 100 if price else None
        else:
            nearest = None
            err_abs = None
            err_pct = None

        rows.append({
            "WAVE节点": name,
            "WAVE价格": price,
            "Replay最近节点": nearest,
            "绝对误差": err_abs,
            "误差%": err_pct,
        })
    return pd.DataFrame(rows)
