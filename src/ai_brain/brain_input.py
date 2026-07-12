"""
Phase AB-1 — Narrative Brain input builder (replaces the starved wrapper input).

AI-0 autopsy proved the old input withheld price (on no-setup scans), candles,
position state, the brain's own history, protected swings, the liquidity draw,
and the bearish half of the toolbox — while feeding the machine's finished
conclusions. This builder gives the brain evidence on BOTH sides and flags
what it could not see (degraded[]), so starvation is visible instead of silent.

Pure assembly from the already-built snapshot + the NA-1 protected-swing state
+ stance memory. No model call here. Never raises.
"""
from toolbox.tool_library import eligible_tools

_TFS = ("15m", "5m", "3m", "1m")


def _candles(snapshot: dict) -> dict:
    """Recent candle context per TF (bodies/wicks/close). Live snapshots carry
    timeframes; trimmed archives do not — absence is reported in degraded[]."""
    tfs = snapshot.get("timeframes", {}) or {}
    out, have_any = {}, False
    for tf in _TFS:
        t = tfs.get(tf, {}) or {}
        recent = t.get("candles") or ([t["last_candle"]] if t.get("last_candle") else [])
        if recent:
            have_any = True
            c = recent[-1]
            out[tf] = {
                "recent": recent[-5:],
                "last_close": c.get("close"),
                "last_high":  c.get("high"),
                "last_low":   c.get("low"),
                "body":  (round(abs(c["close"] - c["open"]), 4)
                          if c.get("close") is not None and c.get("open") is not None else None),
            }
    return {"by_tf": out, "available": have_any}


def _current_price(snapshot: dict, candles: dict) -> "float | None":
    for tf in ("1m", "3m", "5m", "15m"):
        c = candles["by_tf"].get(tf, {})
        if c.get("last_close") is not None:
            return float(c["last_close"])
    ez = (snapshot.get("trade_intent", {}) or {}).get("entry_zone") or {}
    for k in ("current_price",):
        if ez.get(k) is not None:
            return float(ez[k])
    pm = snapshot.get("position_monitor", {}) or {}
    return float(pm["current_price"]) if pm.get("current_price") is not None else None


def _two_sided_inventory(snapshot: dict) -> dict:
    """Both directions' playbook+tool inventory — the bearish half the old
    input never showed. Visibility only; does not change generation."""
    pb = (snapshot.get("playbook", {}) or {}).get("selected_playbook") or "no_playbook"
    tb = snapshot.get("toolbox", {}) or {}
    live = {c.get("tool"): {"score": c.get("score"),
                            "status": c.get("effective_status"),
                            "zone": (c.get("price_level") or {}).get("zone_low") is not None}
            for c in tb.get("tool_candidates", [])}
    inv = {}
    for d in ("bullish", "bearish"):
        tools = eligible_tools(pb, d) if pb != "no_playbook" else []
        inv[d] = [{"tool": t, "live_scored": t in live, **(live.get(t, {}))} for t in tools]
    return {"active_playbook": pb,
            "active_direction": (snapshot.get("playbook", {}) or {}).get("direction"),
            "bullish": inv["bullish"], "bearish": inv["bearish"],
            "note": "active_direction tools are live-scored; opposite side is "
                    "inventory-only until generation is two-sided (later phase)"}


def _position(snapshot: dict) -> dict:
    pm = snapshot.get("position_monitor", {}) or {}
    if not pm.get("has_open_position"):
        return {"position_open": False}
    return {
        "position_open":   True,
        "direction":       pm.get("side"),
        "qty":             pm.get("qty"),
        "entry_price":     pm.get("avg_entry_price"),
        "current_price":   pm.get("current_price"),
        "unrealized_pnl":  pm.get("unrealized_pnl"),
        "stop_reference":  pm.get("stop_reference"),
        "stop_distance":   pm.get("stop_distance"),
        "thesis_health":   (snapshot.get("thesis_monitor", {}) or {}).get("status"),
    }


def _protected(snapshot: dict, price) -> dict:
    ps = snapshot.get("protected_swings", {}) or {}
    ph, pl = ps.get("protected_high"), ps.get("protected_low")
    def rel(level, side):
        if level is None or price is None:
            return "none"
        lv = level["level"]
        if side == "high":
            if price > lv: return "violating"
            return "approaching" if (lv - price) / lv < 0.003 else "below"
        else:
            if price < lv: return "violating"
            return "approaching" if (price - lv) / lv < 0.003 else "above"
    return {
        "protected_high": ph, "protected_high_status": rel(ph, "high"),
        "protected_low":  pl, "protected_low_status":  rel(pl, "low"),
    }


def build_brain_input(snapshot: dict, stance_history: dict) -> dict:
    """Full two-sided evidence payload for the narrative brain. Never raises."""
    try:
        degraded = []
        candles = _candles(snapshot)
        if not candles["available"]:
            degraded.append("candles_unavailable")
        price = _current_price(snapshot, candles)
        if price is None:
            degraded.append("current_price_unavailable")

        sc = snapshot.get("shared_context", {}) or {}
        po3 = snapshot.get("po3", {}) or {}
        liq = snapshot.get("liquidity", {}) or {}
        na = snapshot.get("narrative_authority", {}) or {}
        struct = snapshot.get("structure", {}) or {}
        mr = snapshot.get("market_regime", {}) or {}

        # prior-session / overnight refs do not exist in the data plane (MAP-0)
        degraded.append("prior_session_levels_absent")

        return {
            "timestamp": snapshot.get("timestamp"),
            "session":   snapshot.get("session"),
            "degraded":  degraded,
            "market": {
                "current_price": price,
                "candles": candles["by_tf"],
                "volatility_state": mr.get("volatility_state"),
                "expansion_state":  mr.get("expansion_state"),
            },
            # AI-BRAIN-H2 — structure is WITNESS ONLY and NON-DIRECTIONAL here.
            # The directional fields (bias, directional state) are removed from
            # the LLM payload — they were the AB-5A-S leak that let structure
            # override clean delivery. Only mechanical, non-directional facts
            # (swing levels + break/shift event booleans) remain.
            "STRUCTURE_WITNESS": {
                "_disclaimer": ("STRUCTURE WITNESS ONLY — NOT DIRECTIONAL "
                                "AUTHORITY. Do not use to choose direction; only "
                                "to note possible lag/conflict."),
                **{tf: {"last_swing_high": (struct.get(tf, {}) or {}).get("last_swing_high"),
                        "last_swing_low":  (struct.get(tf, {}) or {}).get("last_swing_low"),
                        "bos_event": bool((struct.get(tf, {}) or {}).get("bos")),
                        "mss_event": bool((struct.get(tf, {}) or {}).get("mss"))}
                   for tf in _TFS},
            },
            "delivery": {
                "state":      sc.get("delivery_state"),
                "confidence": sc.get("delivery_confidence"),
                "continuation_intact": sc.get("continuation_intact"),
                "exhaustion_present":  sc.get("exhaustion_present"),
                "po3_15m": {"phase": (po3.get("15m", {}) or {}).get("phase"),
                            "manipulation_direction": (po3.get("15m", {}) or {}).get("manipulation_direction"),
                            "distribution_direction": (po3.get("15m", {}) or {}).get("distribution_direction")},
                "po3_alignment": po3.get("alignment"),
            },
            "liquidity": {
                "events": [{"tf": tf, "sweep": (liq.get(tf, {}) or {}).get("sweep_direction"),
                            "reclaim": (liq.get(tf, {}) or {}).get("reclaim_detected")}
                           for tf in _TFS if (liq.get(tf, {}) or {}).get("sweep_detected")],
                "nearest_buy_side":  next(((liq.get(tf, {}) or {}).get("nearest_buy_side_liquidity")
                                           for tf in _TFS if (liq.get(tf, {}) or {}).get("nearest_buy_side_liquidity")), None),
                "nearest_sell_side": next(((liq.get(tf, {}) or {}).get("nearest_sell_side_liquidity")
                                           for tf in _TFS if (liq.get(tf, {}) or {}).get("nearest_sell_side_liquidity")), None),
                "active_draw": na.get("active_liquidity_draw"),
            },
            "protected_swings": _protected(snapshot, price),
            "playbook_toolbox": _two_sided_inventory(snapshot),
            "position": _position(snapshot),
            "stance_history": stance_history,
            # AI-BRAIN-H2 — environmental only. The directional NA/council
            # "suggested side" fields are isolated OUT of the LLM payload so the
            # Brain derives direction independently from clean evidence.
            "governance_context": {
                "regime": mr.get("regime_label"),
            },
            "conflicts": na.get("conflict_flags", []),
            "warnings":  na.get("warnings", []),
            # NEWS-1 — non-directional market-awareness context (present only
            # when NEWS_LAYER_ENABLED attached it upstream). Context only: it
            # carries event-risk/awareness, never a direction or a trade.
            **({"news_context": snapshot["news_context"]}
               if isinstance(snapshot.get("news_context"), dict) else {}),
            # HTF-MEM-1 — multi-day context for thesis quality (context only;
            # the Brain may weigh it, it can never be forced by it).
            **({"htf_memory": snapshot["htf_memory"]}
               if isinstance(snapshot.get("htf_memory"), dict) else {}),
            # VOLUME-WITNESS — non-directional participation evidence (present
            # only when VOLUME_WITNESS attached it upstream). Conviction/quality
            # context only; it never carries or implies a direction.
            **({"volume_witness": snapshot["volume_witness"]}
               if isinstance(snapshot.get("volume_witness"), dict) else {}),
        }
    except Exception as exc:  # noqa: BLE001
        return {"timestamp": snapshot.get("timestamp"), "degraded": [f"input_error:{exc}"]}
