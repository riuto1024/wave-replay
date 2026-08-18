from __future__ import annotations

from datetime import date, timedelta
import io
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from wave_replay.data import fetch_binance_klines, load_csv_bytes, resample_ohlcv
from wave_replay.features import add_features, snapshot_features
from wave_replay.swings import detect_swings, structural_nodes, swings_to_frame
from wave_replay.confluence import collect_levels, cluster_zones, zones_to_frame
from wave_replay.elliott import infer_wave_structure
from wave_replay.benchmarks import compare_to_reference, REFERENCE_BENCHMARKS, benchmark_cutoff, benchmark_summary
from wave_replay.report import make_text_report


st.set_page_config(
    page_title="WAVE-Replay V0.2",
    page_icon="〰️",
    layout="wide",
)

st.title("WAVE-Replay V0.2")
st.caption("WAVE 推演引擎行为复现 · V0.2：样本时间对齐 + 一对一节点匹配 + 区域单独评分")


@st.cache_data(ttl=300, show_spinner=False)
def cached_binance(symbol, interval, start, end, max_bars):
    return fetch_binance_klines(
        symbol=symbol,
        interval=interval,
        start=start,
        end=end,
        timezone="8",
        max_bars=max_bars,
    )


def fmt(v):
    if v is None or pd.isna(v):
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.2f}"
    return f"{v:.4f}".rstrip("0").rstrip(".")


def make_chart(df, swings):
    d = df.tail(min(len(df), 350))
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=d["open_time"],
        open=d["open"], high=d["high"], low=d["low"], close=d["close"],
        name="K线",
    ))

    visible_start = d.index.min()
    visible = [p for p in swings if p.idx >= visible_start]
    highs = [p for p in visible if p.kind == "H"]
    lows = [p for p in visible if p.kind == "L"]

    if highs:
        fig.add_trace(go.Scatter(
            x=[p.time for p in highs], y=[p.price for p in highs],
            mode="markers+text",
            text=[f"H/{p.scale}" for p in highs],
            textposition="top center",
            name="Swing High",
        ))
    if lows:
        fig.add_trace(go.Scatter(
            x=[p.time for p in lows], y=[p.price for p in lows],
            mode="markers+text",
            text=[f"L/{p.scale}" for p in lows],
            textposition="bottom center",
            name="Swing Low",
        ))

    fig.update_layout(
        height=620,
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=30, b=10),
        legend_orientation="h",
    )
    return fig


with st.sidebar:
    st.header("运行参数")
    source = st.radio("行情来源", ["Binance公共行情", "上传CSV"], index=0)

    if source == "Binance公共行情":
        quick = st.selectbox("标的", ["BTCUSDT", "ETHUSDT", "自定义"], index=0)
        if quick == "自定义":
            symbol = st.text_input("Binance Symbol", "SOLUSDT").upper().strip()
        else:
            symbol = quick
        interval = st.selectbox("K线周期", ["1d", "4h", "1h"], index=0)

        has_ref = symbol.upper() in REFERENCE_BENCHMARKS
        replay_sample = st.checkbox(
            "WAVE样本复现模式",
            value=has_ref,
            disabled=not has_ref,
            help="自动对齐内置WAVE报告时刻，并用小时K聚合当时可见日K，避免用未来完整日K做历史回放。"
        )

        today = date.today()
        asof = st.date_input("截止日期", value=today)
        lookback_days = st.select_slider(
            "回看天数",
            options=[180, 365, 540, 730, 1000],
            value=730,
        )
        max_bars = st.number_input("最多K线根数", 300, 5000, 2500, 100)
        upload = None
    else:
        symbol = st.text_input("标的名称", "CUSTOM")
        interval = st.selectbox("数据周期说明", ["1d", "4h", "1h", "自定义"], index=0)
        upload = st.file_uploader(
            "上传CSV（date/open/high/low/close/volume）",
            type=["csv"],
        )
        asof = date.today()
        lookback_days = 730
        max_bars = 2500

    st.divider()
    with st.expander("高级：结构节点参数"):
        min_pct = st.slider("最小价格反转比例", 0.002, 0.050, 0.012, 0.001)
        atr_mult = st.slider("最小ATR反转倍数", 0.20, 3.00, 0.75, 0.05)
        tolerance_pct = st.slider("共振聚类容差", 0.001, 0.030, 0.007, 0.001)
        max_nodes = st.slider("结构节点上限", 8, 30, 18, 1)

    run = st.button("运行结构推演", type="primary", use_container_width=True)


if not run:
    st.info("左侧选择参数，然后点击「运行结构推演」。")
    st.markdown(
        """
        **V0.1目标不是做漂亮页面，而是先验证：**
        1. 同一段K线能否稳定找到 WAVE 会使用的显著高低点；
        2. Fibonacci 是否能复算；
        3. 结构节点 + Fib + 成交密集区 + 心理整数位能否形成接近 WAVE 的关键区域；
        4. 用确定性规则给出 Elliott 候选计数和失效位。
        """
    )
    st.stop()


try:
    with st.spinner("读取行情并计算结构…"):
        if source == "Binance公共行情":
            if replay_sample and symbol.upper() in REFERENCE_BENCHMARKS:
                cutoff = benchmark_cutoff(symbol)
                start_ts = cutoff - pd.Timedelta(days=430)
                # 先抓到报告时刻为止的1H数据，再聚合成“当时可见”的日K。
                # 这样不会把报告生成之后的日内高低点偷看进历史样本。
                hourly = cached_binance(
                    symbol, "1h", str(start_ts), str(cutoff),
                    min(15000, max(10500, int(max_bars)))
                )
                raw = resample_ohlcv(hourly, "1D")
                interval_effective = "1d(as-of reconstructed)"
            else:
                end_ts = pd.Timestamp(asof) + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
                start_ts = pd.Timestamp(asof) - pd.Timedelta(days=int(lookback_days))
                raw = cached_binance(symbol, interval, str(start_ts), str(end_ts), int(max_bars))
                interval_effective = interval
        else:
            if upload is None:
                st.error("请先上传CSV。")
                st.stop()
            raw = load_csv_bytes(upload.getvalue())
            interval_effective = interval

        df = add_features(raw)
        swings = detect_swings(df, min_pct=min_pct, atr_mult=atr_mult)
        nodes = structural_nodes(swings, max_nodes=max_nodes)
        levels = collect_levels(df, nodes)
        zones = cluster_zones(df, levels, tolerance_pct=tolerance_pct)
        wave = infer_wave_structure(nodes)
        snap = snapshot_features(df)
        report_text = make_text_report(symbol, df, wave, zones)

except Exception as exc:
    st.exception(exc)
    st.stop()


m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("基准价", fmt(snap["price"]))
m2.metric("5周期", "—" if snap["return_5"] is None else f"{snap['return_5']*100:+.2f}%")
m3.metric("20周期", "—" if snap["return_20"] is None else f"{snap['return_20']*100:+.2f}%")
m4.metric("20周期量比", fmt(snap["volume_ratio_20"]))
m5.metric("日内收盘位置", fmt(snap["close_position_in_day"]))

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["结构图", "结构节点", "关键共振区", "Elliott候选", "WAVE对照"]
)

with tab1:
    st.plotly_chart(make_chart(df, nodes), use_container_width=True)
    st.caption(f"共 {len(df)} 根K线 · 识别 {len(swings)} 个 confirmed swings · 选出 {len(nodes)} 个结构节点")

with tab2:
    sdf = swings_to_frame(nodes)
    if not sdf.empty:
        show = sdf[[
            "time", "kind", "price", "scale", "score",
            "atr_multiple", "max_window", "confirmations", "forced_reason"
        ]].copy()
        st.dataframe(show, use_container_width=True, hide_index=True)
    else:
        st.warning("没有识别到结构节点。")

with tab3:
    zdf = zones_to_frame(zones, 16)
    st.dataframe(zdf, use_container_width=True, hide_index=True)
    st.caption("共振来源包括：Swing结构点、Fibonacci、30/365周期极值、成交密集区、心理整数位。")

with tab4:
    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader(wave.stage)
        st.write(f"模式：`{wave.pattern}`")
        st.write(f"方向：`{wave.direction}`")
        st.write(f"置信度：**{wave.confidence:.0%}**")
        st.write(f"候选失效位：**{fmt(wave.invalidation)}**")
        for note in wave.notes:
            st.write("• " + note)
    with c2:
        st.dataframe(pd.DataFrame(wave.labels), use_container_width=True, hide_index=True)

with tab5:
    if symbol.upper() in REFERENCE_BENCHMARKS:
        ref = REFERENCE_BENCHMARKS[symbol.upper()]
        st.write(
            f"参考 WAVE 样本：{symbol.upper()} · "
            f"报告时间 `{ref['report_time']}` · 基准价 `{ref['basis_price']}`"
        )

        bdf = compare_to_reference(symbol, nodes, zones)
        summary = benchmark_summary(symbol, snap["price"], bdf)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("当前/重建基准价", fmt(snap["price"]))
        c2.metric("WAVE基准价", fmt(summary.get("wave_basis")))
        c3.metric("基准价偏差", "—" if summary.get("basis_diff_pct") is None else f"{summary['basis_diff_pct']:.2f}%")
        c4.metric("命中/未命中", f"{summary.get('hit_count', 0)} / {summary.get('miss_count', 0)}")

        st.dataframe(bdf, use_container_width=True, hide_index=True)

        c5, c6 = st.columns(2)
        c5.metric(
            "命中项目平均误差",
            "—" if summary.get("mean_error_pct") is None else f"{summary['mean_error_pct']:.2f}%"
        )
        c6.metric(
            "命中项目中位误差",
            "—" if summary.get("median_error_pct") is None else f"{summary['median_error_pct']:.2f}%"
        )

        if replay_sample:
            st.success("已启用 WAVE 样本复现模式：报告时间自动对齐，日K由报告时刻之前的小时K重建。")
        elif not summary.get("score_valid"):
            st.warning(
                "当前运行时点与WAVE样本基准价偏差超过1%，本轮误差只供参考。"
                "建议勾选左侧「WAVE样本复现模式」后重跑。"
            )

        st.caption(
            "V0.2不再把支撑区当成单个Swing点比较；结构节点按类型+时间窗一对一匹配，"
            "共振区域单独和WAVE区域比较。"
        )
    else:
        st.info("当前标的没有内置 WAVE 对照样本。")

st.divider()
st.subheader("确定性结构报告")
st.text_area("报告", report_text, height=460)

export = {
    "symbol": symbol,
    "interval": interval_effective,
    "snapshot": snap,
    "wave": wave.to_dict(),
    "nodes": [p.to_dict() for p in nodes],
    "zones": [z.to_dict() for z in zones[:20]],
}
c1, c2, c3 = st.columns(3)
with c1:
    st.download_button(
        "下载结构报告 TXT",
        report_text.encode("utf-8"),
        file_name=f"{symbol}_wave_replay_report.txt",
        mime="text/plain",
        use_container_width=True,
    )
with c2:
    st.download_button(
        "下载结构数据 JSON",
        json.dumps(export, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
        file_name=f"{symbol}_wave_replay.json",
        mime="application/json",
        use_container_width=True,
    )
with c3:
    st.download_button(
        "下载结构节点 CSV",
        swings_to_frame(nodes).to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{symbol}_structural_nodes.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.caption("研究用途，不构成投资建议。V0.1先验证结构节点行为复现，不连接交易账户、不下单。")
