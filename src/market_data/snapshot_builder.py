from datetime import datetime, timezone
from market_data.candle_normalizer import normalize_candles
from market_data.session_engine import get_session_label
from structure.structure_engine import analyze_structure, compute_alignment
from structure.liquidity_engine import analyze_liquidity
from volatility.atr_engine import calculate_atr
from volatility.volatility_classifier import classify_volatility
from volatility.expansion_detector import detect_expansion
from structure.po3_engine import analyze_po3_snapshot
from ai_layer.narrative_builder import build_narrative
from ai_layer.confidence_engine import score_confidence
from ai_layer.ai_snapshot_formatter import format_for_ai
from qualification.trade_qualification_engine import qualify_trade
from playbooks.playbook_classifier import classify_playbook
from risk.risk_governor import evaluate_risk
from toolbox.toolbox_engine import run_toolbox
from ai_layer.discretionary_ai import run_discretionary_ai

TIMEFRAMES = ["15m", "5m", "3m", "1m"]

_NO_MEMORY = {"available": False, "snapshot_count": 0, "global": None, "timeframes": None}


def build_snapshot(raw_data: dict, ref_timestamp: str = None, memory=None, ai_mode_override: str = None) -> dict:
    timeframes = {}
    all_normalized = {}

    for tf in TIMEFRAMES:
        candles = raw_data.get(tf, [])
        if not candles:
            timeframes[tf] = {"last_candle": None, "recent_candles": []}
            all_normalized[tf] = []
            continue

        normalized = normalize_candles(candles, get_session_label)
        all_normalized[tf] = normalized
        timeframes[tf] = {
            "last_candle": normalized[-1],
            "recent_candles": normalized[-5:],
        }

    # Structure analysis runs on the full normalized history per timeframe
    structure = {tf: analyze_structure(all_normalized.get(tf, [])) for tf in TIMEFRAMES}
    structure["alignment"] = compute_alignment({tf: structure[tf] for tf in TIMEFRAMES})

    # Liquidity analysis runs on the full normalized history per timeframe
    liquidity = {tf: analyze_liquidity(all_normalized.get(tf, [])) for tf in TIMEFRAMES}

    # Volatility and expansion: ATR computed first, feeds both classifiers
    volatility = {}
    expansion = {}
    for tf in TIMEFRAMES:
        candles = all_normalized.get(tf, [])
        atr_result = calculate_atr(candles)
        volatility[tf] = classify_volatility(candles, atr_result)
        expansion[tf] = detect_expansion(candles, atr_result)

    # Anchor snapshot to the most granular available last candle
    anchor = None
    for tf in ["1m", "3m", "5m", "15m"]:
        if timeframes.get(tf, {}).get("last_candle"):
            anchor = timeframes[tf]["last_candle"]
            break

    snap_time = ref_timestamp or (
        anchor["timestamp"] if anchor else datetime.now(timezone.utc).isoformat()
    )
    session = anchor["session_label"] if anchor else "unknown"

    # PO3 phase analysis — runs on already-computed mechanical evidence
    po3 = analyze_po3_snapshot(structure, liquidity, volatility, expansion)

    # Memory modifiers from prior snapshots — read BEFORE building narrative/confidence
    memory_mods = memory.get_modifiers() if memory else {}

    # AI layer: narrative (informed by PO3 + memory) → confidence → full context
    narrative  = build_narrative(structure, volatility, expansion, liquidity, po3, session, memory_mods)
    confidence = score_confidence(structure, volatility, expansion, liquidity, session, narrative, po3, memory_mods)

    ai_context = {
        "market_narrative":  narrative["market_narrative"],
        "market_state":      narrative["market_state"],
        "directional_bias":  narrative["directional_bias"],
        "confidence_score":  confidence["confidence_score"],
        "confidence_tier":   confidence["confidence_tier"],
        "trade_personality": narrative["trade_personality"],
        "coherence":         narrative["coherence"],
        "warnings":          narrative["warnings"],
        "summary":           "",  # filled after memory is attached
    }

    snapshot = {
        "timestamp":  snap_time,
        "session":    session,
        "timeframes": timeframes,
        "structure":  structure,
        "volatility": volatility,
        "liquidity":  liquidity,
        "expansion":  expansion,
        "po3":        po3,
        "ai_context": ai_context,
    }

    # Memory context: compares this snapshot to history, then stores it
    snapshot["memory"] = (
        memory.push_and_get_context(snapshot) if memory else _NO_MEMORY.copy()
    )

    # Qualification: reads full snapshot including ai_context + memory
    snapshot["qualification"] = qualify_trade(snapshot)

    # Playbook: reads qualification + all evidence to select tactical game plan
    snapshot["playbook"] = classify_playbook(snapshot)

    # Risk Governor: reads full snapshot including qualification + playbook
    snapshot["risk"] = evaluate_risk(snapshot)

    # Toolbox: reads playbook + risk + all evidence to select entry tools
    snapshot["toolbox"] = run_toolbox(snapshot)

    # AI Discretionary Engine: interprets the full assembled snapshot
    ai_disc, confidence_fusion, ai_debate = run_discretionary_ai(snapshot, mode_override=ai_mode_override)
    snapshot["ai_discretionary"]  = ai_disc
    snapshot["confidence_fusion"] = confidence_fusion
    snapshot["ai_debate"]         = ai_debate

    # Summary generated last so it sees everything
    ai_context["summary"] = format_for_ai(snapshot)

    return snapshot
