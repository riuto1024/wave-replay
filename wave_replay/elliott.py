from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

from .swings import SwingPoint


@dataclass
class WaveInference:
    pattern: str
    direction: str
    stage: str
    confidence: float
    labels: list[dict]
    invalidation: Optional[float]
    notes: list[str]

    def to_dict(self):
        return asdict(self)


def _alternating(points: list[SwingPoint]) -> bool:
    return all(a.kind != b.kind for a, b in zip(points[:-1], points[1:]))


def infer_wave_structure(nodes: list[SwingPoint]) -> WaveInference:
    """
    V0.1：确定性启发式，不调用AI。
    目标是生成 Elliott 候选计数，而不是声称已完美还原 WAVE。
    """
    pts = nodes[-10:]
    if len(pts) < 4:
        return WaveInference(
            pattern="insufficient",
            direction="unknown",
            stage="等待更多结构节点",
            confidence=0.10,
            labels=[],
            invalidation=None,
            notes=["结构节点不足。"],
        )

    # 优先检测最近6点的推动浪候选。
    if len(pts) >= 6:
        six = pts[-6:]
        if _alternating(six):
            kinds = "".join(p.kind for p in six)

            if kinds == "LHLHLH":
                lows = [six[0].price, six[2].price, six[4].price]
                highs = [six[1].price, six[3].price, six[5].price]
                higher_lows = lows[0] < lows[1] < lows[2]
                higher_highs = highs[0] < highs[1] < highs[2]
                if higher_lows and higher_highs:
                    labels = [
                        {"wave": "0", "price": six[0].price, "time": str(six[0].time)},
                        {"wave": "1", "price": six[1].price, "time": str(six[1].time)},
                        {"wave": "2", "price": six[2].price, "time": str(six[2].time)},
                        {"wave": "3", "price": six[3].price, "time": str(six[3].time)},
                        {"wave": "4", "price": six[4].price, "time": str(six[4].time)},
                        {"wave": "5?", "price": six[5].price, "time": str(six[5].time)},
                    ]
                    return WaveInference(
                        pattern="impulse_5_up_candidate",
                        direction="up",
                        stage="5浪推动候选",
                        confidence=0.72,
                        labels=labels,
                        invalidation=six[4].price,
                        notes=[
                            "最近6个结构点形成更高高点与更高低点。",
                            "V0.1仅做候选计数；三铁律需结合更早浪1价格区间继续核验。",
                        ],
                    )

            if kinds == "HLHLHL":
                highs = [six[0].price, six[2].price, six[4].price]
                lows = [six[1].price, six[3].price, six[5].price]
                lower_highs = highs[0] > highs[1] > highs[2]
                lower_lows = lows[0] > lows[1] > lows[2]
                if lower_highs and lower_lows:
                    labels = [
                        {"wave": "0", "price": six[0].price, "time": str(six[0].time)},
                        {"wave": "1", "price": six[1].price, "time": str(six[1].time)},
                        {"wave": "2", "price": six[2].price, "time": str(six[2].time)},
                        {"wave": "3", "price": six[3].price, "time": str(six[3].time)},
                        {"wave": "4", "price": six[4].price, "time": str(six[4].time)},
                        {"wave": "5?", "price": six[5].price, "time": str(six[5].time)},
                    ]
                    return WaveInference(
                        pattern="impulse_5_down_candidate",
                        direction="down",
                        stage="5浪下跌候选",
                        confidence=0.72,
                        labels=labels,
                        invalidation=six[4].price,
                        notes=[
                            "最近6个结构点形成更低高点与更低低点。",
                            "若浪4与浪2发生规则禁止的重叠，需重新计数。",
                        ],
                    )

    # ABC：最近4点 H-L-H-L 或 L-H-L-H。
    four = pts[-4:]
    if _alternating(four):
        kinds = "".join(p.kind for p in four)
        if kinds == "HLHL":
            labels = [
                {"wave": "起点", "price": four[0].price, "time": str(four[0].time)},
                {"wave": "A", "price": four[1].price, "time": str(four[1].time)},
                {"wave": "B", "price": four[2].price, "time": str(four[2].time)},
                {"wave": "C?", "price": four[3].price, "time": str(four[3].time)},
            ]
            return WaveInference(
                pattern="abc_down_candidate",
                direction="down",
                stage="ABC调整 / C段候选",
                confidence=0.62,
                labels=labels,
                invalidation=four[2].price,
                notes=["最近四个结构节点满足 H-L-H-L 的修正轮廓。"],
            )
        if kinds == "LHLH":
            labels = [
                {"wave": "起点", "price": four[0].price, "time": str(four[0].time)},
                {"wave": "A", "price": four[1].price, "time": str(four[1].time)},
                {"wave": "B", "price": four[2].price, "time": str(four[2].time)},
                {"wave": "C?", "price": four[3].price, "time": str(four[3].time)},
            ]
            return WaveInference(
                pattern="abc_up_candidate",
                direction="up",
                stage="ABC反弹 / C段候选",
                confidence=0.62,
                labels=labels,
                invalidation=four[2].price,
                notes=["最近四个结构节点满足 L-H-L-H 的修正轮廓。"],
            )

    last = pts[-1]
    return WaveInference(
        pattern="complex_or_unconfirmed",
        direction="unknown",
        stage="复杂调整 / 尚未确认",
        confidence=0.35,
        labels=[
            {"wave": "最新结构点", "price": last.price, "time": str(last.time)}
        ],
        invalidation=None,
        notes=["当前结构不满足V0.1的简单推动或ABC模板，保留为复杂结构。"],
    )
