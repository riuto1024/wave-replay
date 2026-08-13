from __future__ import annotations

from .features import snapshot_features
from .elliott import WaveInference
from .confluence import Zone


def _pct(v):
    if v is None:
        return "—"
    return f"{v * 100:+.2f}%"


def _num(v):
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.2f}"
    return f"{v:.4f}".rstrip("0").rstrip(".")


def make_text_report(symbol: str, df, wave: WaveInference, zones: list[Zone]) -> str:
    s = snapshot_features(df)
    supports = [z for z in zones if z.side == "support"][:3]
    resist = [z for z in zones if z.side == "resistance"][:3]

    lines = [
        f"{symbol} · WAVE-Replay V0.1",
        "=" * 56,
        f"基准时间：{s['as_of']}",
        f"基准价：{_num(s['price'])}",
        "",
        "【基础市场特征】",
        f"5周期动量：{_pct(s['return_5'])}",
        f"20周期动量：{_pct(s['return_20'])}",
        f"20周期量比：{_num(s['volume_ratio_20'])}",
        f"日内收盘位置：{_num(s['close_position_in_day'])}",
        f"30周期高/低：{_num(s['high_30'])} / {_num(s['low_30'])}",
        f"365周期高/低：{_num(s['high_365'])} / {_num(s['low_365'])}",
        "",
        "【Elliott候选结构】",
        f"模式：{wave.pattern}",
        f"阶段：{wave.stage}",
        f"方向：{wave.direction}",
        f"置信度：{wave.confidence:.0%}",
        f"候选失效位：{_num(wave.invalidation)}",
    ]
    lines += [f"- {n}" for n in wave.notes]

    lines += ["", "【共振支撑区】"]
    if supports:
        for z in supports:
            lines.append(
                f"- {_num(z.low)} ~ {_num(z.high)} | score={z.score:.2f} | "
                + ", ".join(z.sources[:5])
            )
    else:
        lines.append("- 暂未识别到高分支撑区")

    lines += ["", "【共振阻力区】"]
    if resist:
        for z in resist:
            lines.append(
                f"- {_num(z.low)} ~ {_num(z.high)} | score={z.score:.2f} | "
                + ", ".join(z.sources[:5])
            )
    else:
        lines.append("- 暂未识别到高分阻力区")

    lines += [
        "",
        "【说明】",
        "V0.1用于行为复现研究：先复现结构节点、Fibonacci、共振区和失效规则。",
        "当前Elliott计数为确定性启发式候选，不等同于WAVE内部私有算法，也不构成投资建议。",
    ]
    return "\n".join(lines)
