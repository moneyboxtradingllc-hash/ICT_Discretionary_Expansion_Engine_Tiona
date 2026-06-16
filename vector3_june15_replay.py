"""VECTOR-3 June-15 replay — alignment / delivery-state flicker, before vs after.

Reconstructs the real per-timeframe candle series for 2026-06-15 from the
archived ai_brain input payloads (each scan carries the latest candle per TF),
then re-runs the exact PO3 evidence path twice over every 1m scan:

  BEFORE : VECTOR3_MAGNITUDE_GATE=off, no stability manager  (legacy)
  AFTER  : gate on + Po3StabilityManager (hysteresis)

Reports alignment flip rate, 1m delivery-phase flip rate, and the 17:30-17:41
flat-tape window behaviour. Analysis only; no LLM, no trades, no file writes.
"""
import os, sys, glob, json

sys.path.insert(0, "src")
sys.stdout.reconfigure(encoding="utf-8")

from market_data.candle_normalizer import normalize_candle
from structure.structure_engine import analyze_structure
from structure.liquidity_engine import analyze_liquidity
from volatility.atr_engine import calculate_atr
from volatility.volatility_classifier import classify_volatility
from volatility.expansion_detector import detect_expansion
from structure.po3_engine import analyze_po3_snapshot

TFS = ["15m", "5m", "3m", "1m"]
WIN_LOOKBACK = 60          # trailing candles fed per TF (same for both passes)
FLAT_LO, FLAT_HI = "17:30:00", "17:41:00"


def reconstruct():
    series = {tf: {} for tf in TFS}
    for fp in sorted(glob.glob("data/ai_brain/20260615_*_QQQ.json")):
        d = json.load(open(fp, encoding="utf-8"))
        candles = (((d.get("input_payload") or {}).get("market") or {}).get("candles") or {})
        for tf in TFS:
            for cd in (candles.get(tf, {}) or {}).get("recent", []) or []:
                if isinstance(cd, dict) and "timestamp" in cd:
                    series[tf][cd["timestamp"]] = cd
    return {tf: [series[tf][k] for k in sorted(series[tf])] for tf in TFS}


def renorm(c):
    # reconstructed candles are already normalized dicts; pass through normalizer
    # to guarantee identical field derivation as the live pipeline.
    return normalize_candle(c, c.get("session_label", "sess"))


def evidence_for_scan(series, upto_ts, gate_on):
    structure, liquidity, volatility, expansion = {}, {}, {}, {}
    for tf in TFS:
        hist = [renorm(c) for c in series[tf] if c["timestamp"] <= upto_ts][-WIN_LOOKBACK:]
        structure[tf] = analyze_structure(hist)
        liquidity[tf] = analyze_liquidity(hist)
        atr = calculate_atr(hist)
        volatility[tf] = classify_volatility(hist, atr)
        expansion[tf] = detect_expansion(hist, atr, tf if gate_on else None)
    structure["alignment"] = None
    return structure, liquidity, volatility, expansion


def run_pass(series, scan_times, gate_on, use_manager):
    os.environ["VECTOR3_MAGNITUDE_GATE"] = "on" if gate_on else "off"
    mgr = None
    if use_manager:
        from structure.po3_alignment_manager import Po3StabilityManager
        mgr = Po3StabilityManager()
    rows = []
    for t in scan_times:
        s, l, v, e = evidence_for_scan(series, t, gate_on)
        po3 = analyze_po3_snapshot(s, l, v, e)
        if mgr is not None:
            po3 = mgr.update(po3)
        rows.append({
            "t": t,
            "alignment": po3.get("alignment"),
            "phase_1m": po3.get("1m", {}).get("phase"),
            "phase_5m": po3.get("5m", {}).get("phase"),
            "kappa_1m": e["1m"].get("kappa"),
            "disp_1m": e["1m"].get("displacement_detected"),
        })
    return rows


def flips(rows, key):
    return sum(1 for i in range(1, len(rows)) if rows[i][key] != rows[i - 1][key])


def summarize(label, rows):
    n = len(rows)
    af, pf = flips(rows, "alignment"), flips(rows, "phase_1m")
    fda = sum(1 for r in rows if r["alignment"] == "full_distribution_alignment")
    print(f"\n[{label}] scans={n}")
    print(f"  alignment flips        : {af}  ({af/(n-1)*100:.1f}% of transitions)")
    print(f"  1m delivery-phase flips: {pf}  ({pf/(n-1)*100:.1f}% of transitions)")
    print(f"  full_distribution scans: {fda}")
    return af, pf, fda


def window_dump(label, rows):
    w = [r for r in rows if FLAT_LO <= r["t"][11:19] <= FLAT_HI]
    print(f"\n  17:30-17:41 flat window [{label}] (n={len(w)}):")
    for r in w:
        print(f"    {r['t'][11:16]}  align={r['alignment']:<28} 1m={r['phase_1m']:<14}"
              f" kappa={r['kappa_1m']} disp={r['disp_1m']}")
    fda = sum(1 for r in w if r["alignment"] == "full_distribution_alignment")
    aflip = flips(w, "alignment")
    print(f"    -> window alignment flips={aflip}  full_distribution scans={fda}")
    return aflip, fda


def main():
    series = reconstruct()
    for tf in TFS:
        print(f"reconstructed {tf}: {len(series[tf])} candles")
    scan_times = [c["timestamp"] for c in series["1m"]]
    # need enough history for ATR; skip first few
    scan_times = scan_times[5:]

    before = run_pass(series, scan_times, gate_on=False, use_manager=False)
    after = run_pass(series, scan_times, gate_on=True, use_manager=True)

    print("\n" + "=" * 70)
    print("VECTOR-3 JUNE-15 REPLAY — FULL SESSION")
    print("=" * 70)
    b = summarize("BEFORE (legacy)", before)
    a = summarize("AFTER (gate+hysteresis)", after)

    print("\n" + "=" * 70)
    print("17:30-17:41 FLAT-TAPE WINDOW")
    print("=" * 70)
    bw = window_dump("BEFORE", before)
    aw = window_dump("AFTER", after)

    print("\n" + "=" * 70)
    print("DELTA")
    print("=" * 70)
    print(f"  alignment flips      : {b[0]} -> {a[0]}   ({b[0]-a[0]:+d})")
    print(f"  1m delivery flips    : {b[1]} -> {a[1]}   ({b[1]-a[1]:+d})")
    print(f"  full_distribution    : {b[2]} -> {a[2]} scans")
    print(f"  window align flips   : {bw[0]} -> {aw[0]}")
    print(f"  window full_distrib  : {bw[1]} -> {aw[1]} scans")
    # restore default
    os.environ.pop("VECTOR3_MAGNITUDE_GATE", None)


if __name__ == "__main__":
    main()
