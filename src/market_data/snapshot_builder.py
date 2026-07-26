from datetime import datetime, timezone
from market_data.candle_normalizer import normalize_candles
from market_data.session_engine import get_session_label
from structure.structure_engine import analyze_structure, compute_alignment
from structure.liquidity_engine import analyze_liquidity
from volatility.atr_engine import calculate_atr
from volatility.volatility_classifier import classify_volatility
from volatility.expansion_detector import detect_expansion
from structure.po3_engine import analyze_po3_snapshot
from structure.manipulation_detector import detect_manipulation
from structure.displacement_detector import detect_displacement
from structure.market_context import analyze_market_context
from regime_classification.structure_hierarchy import (
    htf_authority, classify_relationship,
)
from market_commander.market_commander import build_market_commander_matrix  # MC Phase B1 (observe-only)
from ai_layer.narrative_builder import build_narrative
from ai_layer.confidence_engine import score_confidence
from ai_layer.ai_snapshot_formatter import format_for_ai
from qualification.trade_qualification_engine import qualify_trade
from playbooks.playbook_classifier import classify_playbook
from risk.risk_governor import evaluate_risk
from toolbox.toolbox_engine import run_toolbox
# TIER-2A (2026-07-10) — legacy AI wrapper (discretionary_ai / debate / fusion)
# retired. The sovereign ECU Brain is the single AI; its thesis exercises
# authority upstream (qualification/playbook/toolbox direction).
from regime_classification.regime_classifier import classify_regime
from regime_authority.regime_permission_matrix import evaluate_regime_permissions
# ── Phase PIPE-1 — evidence layers the canonical Brain authors from. These were
# previously built in scan_loop AFTER build_snapshot, starving the consumed ECU
# thesis. They are now assembled inside build_snapshot BEFORE the single Brain call.
from narrative_authority.narrative_engine import build_narrative as build_narrative_authority
from narrative_authority.protected_swings import ProtectedSwingTracker
from shared_context.shared_market_context import build_shared_market_context

TIMEFRAMES = ["15m", "5m", "3m", "1m"]

_NO_MEMORY = {"available": False, "snapshot_count": 0, "global": None, "timeframes": None}


def build_snapshot(
    raw_data: dict,
    ref_timestamp: str = None,
    memory=None,
    experience_summary: dict = None,
    prior_memory_search: dict = None,
    prior_dashboard: dict = None,
    thesis_engine=None,
    symbol: str = None,
    swing_tracker=None,
    po3_stability=None,
    expansion_stability=None,
    capital_report=None,
    htf_context=None,
) -> dict:
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

    # Standing directional authority, derived from `structure` alone so it is
    # available to every layer below without inverting the dependency chain.
    _ctx_series = next((all_normalized[tf] for tf in ("1m", "3m", "5m", "15m")
                        if all_normalized.get(tf)), None)
    _last_price = _ctx_series[-1]["close"] if _ctx_series else None
    _authority = htf_authority(structure.get("15m"), _last_price, "15m")
    _relationship = classify_relationship(
        _authority, str((structure.get("5m") or {}).get("bias") or "neutral").lower())

    # Volatility and expansion: ATR computed first, feeds both classifiers
    volatility = {}
    expansion = {}
    for tf in TIMEFRAMES:
        candles = all_normalized.get(tf, [])
        atr_result = calculate_atr(candles)
        volatility[tf] = classify_volatility(candles, atr_result)
        # VECTOR-3: tf enables magnitude gate. LEG-SCOPE: structure[tf] supplies
        # the pivot that bounds the conviction ratios to the current auction leg.
        expansion[tf] = detect_expansion(candles, atr_result, tf, structure.get(tf))
        # MANIP-CONFLUENCE: manipulation is a phase, not a closing-bar event.
        # Attached to liquidity so po3_engine keeps scoring from processed
        # evidence rather than raw candles.
        if isinstance(liquidity.get(tf), dict):
            liquidity[tf]["manipulation"] = detect_manipulation(
                candles, atr_result.get("atr"))
        # DISPLACEMENT-CONFLUENCE: displacement_detected is a bare bool and
        # cannot separate a nudge from a drive that tears gaps in the tape.
        if isinstance(expansion.get(tf), dict):
            expansion[tf]["displacement"] = detect_displacement(
                candles, structure.get(tf), atr_result.get("atr"), expansion[tf],
                authority=_authority)

    # PERCEPTION-1 — expansion state hysteresis (VECTOR-3 analogue). The live
    # loop passes its persistent instance; one-shot callers get no stabilizer
    # (bit-for-bit legacy). Debounces the flickering per-TF expansion `state`
    # so a one-scan threshold crossing no longer overrides a stable state.
    if expansion_stability is not None:
        expansion = expansion_stability.update(expansion)

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

    # PO3 phase analysis — runs on already-computed mechanical evidence.
    # Reconciled against the authority established above: additive only, it
    # annotates how each phase sits inside the authority and never rewrites it.
    po3 = analyze_po3_snapshot(structure, liquidity, volatility, expansion,
                               authority=_authority,
                               relationship=_relationship["relationship"])

    # VECTOR-3 — stateful stability layer. The pure engine above re-derives phases
    # and alignment from scratch each scan; the manager (when the live loop passes
    # its persistent instance) applies the phase dead-band + alignment hysteresis
    # so a single sub-floor 1m flip can no longer rewrite global alignment. When no
    # instance is passed, po3 is unchanged (pure pass-through).
    if po3_stability is not None:
        po3 = po3_stability.update(po3)

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
        # NARRATIVE-AUDIT — decision-reason transparency (observe-only telemetry)
        "narrative_reason":     narrative.get("narrative_reason"),
        "narrative_driver_tf":  narrative.get("narrative_driver_tf"),
        "summary":           "",  # filled after memory is attached
    }

    # AI_CONTEXT-AUTHORITY (2026-07-09) — TRUTH-IN-LABELLING. Despite the name,
    # EVERY ai_context field is MECHANICALLY authored: build_narrative() /
    # score_confidence() read only structure/volatility/expansion/liquidity/po3.
    # The true AI Brain lives in snapshot['ai_brain'] / ['brain_thesis'] /
    # ['thesis_state']. This metadata marks each field's real author so no
    # consumer can mistake a mechanical reading for AI authority. Decision
    # consumers demote these to witness when the Brain is sovereign (see
    # shared_context.mechanical_judges.mechanical_context_witness).
    ai_context["_authorship"] = {
        "market_narrative":  "mechanical_derived",
        "market_state":      "mechanical_derived",
        "directional_bias":  "mechanical_derived",
        "confidence_score":  "mechanical_derived",
        "confidence_tier":   "mechanical_derived",
        "trade_personality": "mechanical_derived",
        "coherence":         "mechanical_sensor",
        "warnings":          "mechanical_sensor",
        "narrative_reason":     "telemetry",
        "narrative_driver_tf":  "telemetry",
        "summary":              "telemetry",
    }
    ai_context["ai_context_is_mechanical_witness"] = True

    snapshot = {
        "timestamp":  snap_time,
        "session":    session,
        "symbol":     symbol,
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

    # Regime Classifier (Phase 5A, moved up in 5F): labels the environment.
    # Confidence-side authority unchanged (observe_only, confidence_modifier=0).
    # Phase 5F.2 grants regime CONSTRAINT authority via the permission matrix below.
    snapshot["market_regime"] = classify_regime(snapshot, all_normalized)

    # ── MARKET-CONTEXT — stage 1 authority. Must follow classify_regime, which
    # it consumes rather than duplicates. Adds what nothing upstream provides:
    # retracement as an environment, the dealing range / premium-discount, and
    # the authority downstream asks before assigning direction to a local event.
    snapshot["market_context"] = analyze_market_context(
        structure, liquidity, expansion, po3, snapshot["market_regime"],
        last_price=_last_price)

    # ── Phase NEWS-1 — News Intelligence pre-pass (gated NEWS_LAYER_ENABLED) ───
    # Attaches non-directional market-awareness context (scheduled events,
    # breaking news, event-risk state) so the Brain can weigh it. Runs BEFORE the
    # ECU pre-pass so the Brain receives it. News never authors direction or
    # trades. When OFF, skipped entirely — pipeline bit-for-bit unchanged.
    from news.news_engine import news_enabled, build_news_context
    if news_enabled():
        snapshot["news_context"] = build_news_context(snapshot.get("timestamp"))

    # ── VOLUME-WITNESS — participation sense organ (gated VOLUME_WITNESS) ─────
    # Non-directional participation evidence attached BEFORE the ECU pre-pass:
    # per-TF relative volume + z-score + same-minute-of-day percentile (replay-
    # built baseline table) + sweep/displacement association (EXISTING sensors'
    # events only — no re-detection) + IEX venue provenance. WITNESS ONLY: no
    # gate/risk/qualification/decision path reads it (test-locked). When OFF,
    # skipped entirely — pipeline bit-for-bit unchanged.
    from market_data.volume_witness import volume_witness_enabled, build_volume_witness
    if volume_witness_enabled():
        snapshot["volume_witness"] = build_volume_witness(
            all_normalized, liquidity=liquidity, expansion=expansion,
            symbol=symbol or snapshot.get("symbol"))

    # ── HTF-MEM-1 — higher-timeframe memory (CONTEXT ONLY) ─────────────────────
    # Multi-day context (previous day/session, weekly direction, gap, untapped
    # liquidity) computed by the scan loop's HtfMemoryEngine and attached BEFORE
    # the ECU pre-pass so the Brain can weigh it. It informs thesis quality and
    # warns about conflict; it may NOT execute, veto, or force direction.
    if isinstance(htf_context, dict):
        snapshot["htf_memory"] = htf_context

    # ── Phase PIPE-1 — assemble the load-bearing evidence the Brain authors from
    # BEFORE the single canonical Brain call. Previously protected_swings,
    # narrative_authority and shared_context were built in scan_loop AFTER this
    # function returned, so the consumed ECU thesis saw delivery.state=None,
    # protected_swings=none and active_draw=None (the upstream ordering inversion).
    # The protected-swing tracker is stateful: the live loop passes its persistent
    # instance; one-shot callers get a transient tracker. This is the ONLY place
    # the tracker is advanced per scan.
    #
    # NOTE: shared_context here carries the qualification-INDEPENDENT delivery view
    # the Brain needs (delivery_state / exhaustion_present / po3). Its opportunity
    # view (qualification / playbook / setup_age) is necessarily still default at
    # this point and is rebuilt downstream once qualification + setup_lifecycle
    # exist; nothing reads that view before the rebuild.
    _swings = swing_tracker if swing_tracker is not None else ProtectedSwingTracker()
    snapshot["protected_swings"]    = _swings.update(snapshot)
    snapshot["narrative_authority"] = build_narrative_authority(
        snapshot, snapshot["protected_swings"])

    # HTF-MEM-1: conflict WARNING flags (context, not veto) — HTF bias vs the
    # narrative direction, computed pre-Brain so the Brain sees the warning too.
    if isinstance(htf_context, dict) and htf_context.get("htf_bias") in ("bullish", "bearish"):
        _na_dir = (snapshot["narrative_authority"] or {}).get("narrative_direction")
        flags = []
        if _na_dir in ("bullish", "bearish") and _na_dir != htf_context["htf_bias"]:
            flags.append(f"htf_bias_{htf_context['htf_bias']}_vs_narrative_{_na_dir}")
        _gap = (htf_context.get("gap_context") or {})
        if _gap.get("side") in ("gap_up", "gap_down") and not _gap.get("filled"):
            flags.append(f"unfilled_{_gap['side']}")
        htf_context["htf_conflict_flags"] = flags
    snapshot["shared_context"]      = build_shared_market_context(
        snapshot, symbol or snapshot.get("symbol"))

    # ── Phase AB-5B — canonical ECU Brain call (gated BRAIN_ECU_MODE, default off)
    # Runs AFTER the evidence above and BEFORE the intelligence consumers, so the
    # consumed thesis is fully-fed. When OFF, skipped entirely and the
    # mechanical-owned pipeline is unchanged (bit-for-bit).
    from ai_brain.ecu import ecu_enabled, produce_thesis
    if ecu_enabled():
        candidate = produce_thesis(snapshot)
        snapshot["candidate_thesis"] = candidate
        snapshot["brain_thesis"] = candidate   # shadow default: pipeline bit-for-bit unchanged

        # ── Phase AB-7 — Persistent Thesis Lifecycle (gated THESIS_LIFECYCLE_MODE) ──
        # The Brain produces a CANDIDATE every scan; the lifecycle engine maintains a
        # persisted ACTIVE thesis (continue/strengthen/weaken/invalidate/replace). In
        # shadow it only observes; in enforce it stabilizes brain_thesis so the
        # consumers stop flickering on one-scan evidence noise.
        from ai_brain.thesis_lifecycle import (
            lifecycle_enabled, enforce_mode, extract_evidence, ThesisLifecycleEngine,
            thesis_state,
        )
        if lifecycle_enabled():
            engine = thesis_engine or ThesisLifecycleEngine()
            snapshot["thesis_lifecycle"] = engine.update(
                candidate, extract_evidence(snapshot, candidate), snapshot.get("timestamp"),
            )
            # ── Phase AB-7.3a — read-only thesis state for downstream consumers ──
            # Exposes the stabilized thesis/playbook state (status, age, confidence
            # trend) so qualification/readiness/gate can consume it. Read-only; no
            # behavioral change on its own (consumers gate their own usage).
            snapshot["thesis_state"] = thesis_state(snapshot["thesis_lifecycle"])
            if enforce_mode():
                stabilized = engine.as_brain_thesis()
                if stabilized is not None:
                    snapshot["brain_thesis"] = stabilized

    # Qualification: validator. Opportunity SCORE is mechanical; direction is
    # owned by the Brain thesis under ECU mode (see _direction_with_source).
    snapshot["qualification"] = qualify_trade(snapshot)

    # Playbook: validator/ranker. Direction owned by Brain thesis under ECU mode.
    snapshot["playbook"] = classify_playbook(snapshot)

    # Regime Permission Matrix (Phase 5F.2): constraint authority.
    # Controls permissions (playbooks, risk cap, trigger strictness, setup age)
    # — NEVER confidence scores. Enforced in order_builder + execution_gate.
    snapshot["regime_permissions"] = evaluate_regime_permissions(snapshot)

    # Risk Governor: reads full snapshot including qualification + playbook
    snapshot["risk"] = evaluate_risk(snapshot)

    # Toolbox: reads playbook + risk + all evidence to select entry tools
    snapshot["toolbox"] = run_toolbox(snapshot)

    # ── ADAPTIVE-3 — Adaptive Policy Report (OBSERVE_ONLY / DEFENSIVE_ONLY) ────
    # Reads the symbol-native performance tables for the CURRENT candidate
    # (playbook/tool/session/regime/volatility) and reports expectancy grades +
    # recommendation flags. Recommendation-only: it authorizes/blocks/overrides
    # NOTHING (authority_level=observe_only). Built AFTER toolbox so all five
    # candidate dimensions exist. Never raises.
    from adaptive_learning.adaptive_policy_engine import generate_adaptive_policy_report
    _regime = snapshot.get("market_regime", {}) or {}
    # CAPITAL-1: the scan loop computes the capital report once per scan and
    # passes it here; capital rides the policy as a DEFENSIVE evidence source.
    snapshot["capital_intelligence"] = capital_report
    snapshot["adaptive_policy"] = generate_adaptive_policy_report({
        "symbol":     symbol or snapshot.get("symbol"),
        "playbook":   (snapshot.get("playbook", {}) or {}).get("selected_playbook"),
        "tool":       (snapshot.get("toolbox", {}) or {}).get("preferred_tool"),
        "session":    snapshot.get("session"),
        "regime":     _regime.get("regime_family"),
        "volatility": _regime.get("volatility_state"),
    }, capital=capital_report)

    # ── ADAPTIVE-4 — Bounded Mutation Engine (SHADOW MODE / DEFENSIVE_ONLY) ────
    # Computes the DEFENSIVE_ONLY mutations the policy WOULD apply to the live
    # candidate (confidence penalty / size halving / soft veto). SHADOW: computed,
    # visible, and persisted with the snapshot, but NOT enforced — execution reads
    # the original authority. Boosts are ignored. Never raises. qty is None here
    # (sizing happens at execution); the size rule therefore no-ops in-snapshot.
    from adaptive_learning.adaptive_mutation_engine import mutate_candidate
    _qual = snapshot.get("qualification", {}) or {}
    snapshot["adaptive_mutation"] = mutate_candidate(
        {
            "confidence":           (snapshot.get("ai_context", {}) or {}).get("confidence_score"),
            "qty":                  None,
            "playbook":             (snapshot.get("playbook", {}) or {}).get("selected_playbook"),
            "tool":                 (snapshot.get("toolbox", {}) or {}).get("preferred_tool"),
            "qualification_status": _qual.get("status"),
            "direction":            _qual.get("direction"),
        },
        snapshot["adaptive_policy"],
    )

    # ── ADAPTIVE-5 — Live Mutation Authority (LIVE / DEFENSIVE_ONLY) ───────────
    # Promotes the shadow mutation to a LIVE defensive OVERLAY: exposes
    # adaptive_live_authority / adaptive_confidence / adaptive_block / adaptive_size
    # WITHOUT overwriting ai_context, qualification, playbook, tool, direction, the
    # Brain confidence, or the risk governor. Downstream layers may READ these to
    # become STRICTER only (confidence never raised, size never invented, block can
    # only add a no-trade reason). Never raises.
    from adaptive_learning.adaptive_live_authority import apply_adaptive_live_authority
    apply_adaptive_live_authority(snapshot)

    # Experience Intelligence (Phase 3A): OBSERVE_ONLY context from previous scan.
    # confidence_modifier is always 0 and must never influence toolbox or decisions.
    if experience_summary:
        snapshot["experience_summary"] = experience_summary

    # Phase 5E.3 — inject prior-scan intelligence so AI input sees real data.
    # These are 1-scan stale but far better than empty dicts.
    # scan_loop.py overwrites them with fresh values after this function returns.
    if prior_memory_search:
        snapshot["memory_search"] = prior_memory_search
    if prior_dashboard:
        snapshot["performance_dashboard"] = prior_dashboard

    # TIER-2A (2026-07-10) — the legacy AI wrapper call
    # (ai_discretionary / confidence_fusion / ai_debate) is RETIRED. Downstream
    # readers tolerate absence: Commander council testimony reports an explicit
    # missing_reason; the ADAPTIVE-6 confidence overlay finds no target (its
    # guard makes it a recorded no-op); decision.confidence reports 0.

    # Summary generated last so it sees everything
    ai_context["summary"] = format_for_ai(snapshot)

    # ── MARKET COMMANDER (Phase B1) — OBSERVE-ONLY telemetry ──────────────────
    # Built LAST, after every evidence layer + Brain/thesis/qualification/risk/
    # playbook/toolbox exist, so the matrix reflects the full picture. It
    # authorizes/blocks/overrides NOTHING (authority_level=observe_only); it only
    # unifies the scan into one state matrix and flags contradictions.
    snapshot["market_commander"] = build_market_commander_matrix(snapshot)

    return snapshot
