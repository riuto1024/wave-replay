import numpy as np
import pandas as pd

from wave_replay.features import add_features
from wave_replay.swings import detect_swings, structural_nodes
from wave_replay.confluence import collect_levels, cluster_zones
from wave_replay.elliott import infer_wave_structure
from wave_replay.report import make_text_report


def synthetic_data(n=500):
    rng = np.random.default_rng(42)
    t = pd.date_range("2025-01-01", periods=n, freq="D")
    trend = 100 + np.linspace(0, 60, n)
    cyc = 12 * np.sin(np.linspace(0, 12*np.pi, n))
    noise = rng.normal(0, 1.8, n)
    close = trend + cyc + noise
    open_ = close + rng.normal(0, 1.0, n)
    high = np.maximum(open_, close) + rng.uniform(0.5, 3.0, n)
    low = np.minimum(open_, close) - rng.uniform(0.5, 3.0, n)
    vol = rng.integers(1000, 5000, n)
    return pd.DataFrame({
        "open_time": t,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol,
    })


if __name__ == "__main__":
    df = add_features(synthetic_data())
    swings = detect_swings(df)
    nodes = structural_nodes(swings)
    zones = cluster_zones(df, collect_levels(df, nodes))
    wave = infer_wave_structure(nodes)
    report = make_text_report("SYNTH", df, wave, zones)

    assert len(swings) > 5
    assert len(nodes) > 3
    assert len(zones) > 0
    assert "WAVE-Replay V0.1" in report
    print("SMOKE TEST PASSED")
    print(f"bars={len(df)} swings={len(swings)} nodes={len(nodes)} zones={len(zones)} wave={wave.pattern}")
