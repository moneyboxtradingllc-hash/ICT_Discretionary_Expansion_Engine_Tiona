"""
Phase 1P — Live Scan Loop.
Runs repeated live scans, keeps MarketMemory alive across iterations,
and controls external AI refresh cadence.

No execution. No order routing. No broker actions. Scan only.
"""
import os
import sys
import time
from datetime import datetime

import pytz
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.snapshot_builder    import build_snapshot
from state.market_memory             import MarketMemory
from data_feed                       import get_provider
from data_feed.provider_interface    import DataFeedError
from data_feed.timeframe_builder     import build_timeframes
from data_feed.market_clock          import is_within_scan_window
from live_scan.snapshot_store              import save_snapshot
from live_scan.ai_refresh_controller       import AIRefreshController
from state_transitions.transition_engine   import analyze_transition
from setup_lifecycle.setup_tracker         import SetupTracker
from decision_authority.decision_engine    import make_decision
from execution_gate.execution_gate         import evaluate_gate
from trade_intent.intent_builder           import build_intent
from intent_scoring.intent_scorer          import score_intent
from intent_archive.intent_archive            import update_archive
from paper_execution.execution_engine         import attempt_paper_execution
from paper_execution.position_monitor              import monitor_paper_position
from paper_execution.stop_enforcer                 import enforce_stop
from operational_readiness.readiness_checklist     import run_readiness_check
from operational_readiness.activation_controller   import determine_activation
from paper_activation.activation_plan              import build_activation_plan
from paper_activation.activation_runner            import run_activation
from paper_activation.activation_report            import log_activation_event
from experience_intelligence.experience_summary     import build_experience_summary
from experience_intelligence.experience_report      import build_experience_report
from experience_intelligence.experience_correlation import build_correlation_for_symbol
from experience_intelligence.correlation_report     import build_correlation_report
from paper_execution.trade_reconciliation           import reconcile_trade
from paper_execution.pending_order_lifecycle        import cancel_pending_entry_order_if_setup_dead
from paper_execution.trade_manager                  import manage_open_trade
from ai_layer.ai_snapshot_formatter                 import (
    format_decision_line, format_gate_line, format_intent_line,
    format_score_line, format_archive_line, format_paper_execution_line,
    format_position_monitor_line, format_stop_enforcer_line,
    format_operational_readiness_line, format_activation_line,
    format_paper_activation_line, format_experience_line,
    format_experience_link_line, format_correlation_line,
    format_broker_stop_line,
    format_regime_line,
    format_ai_feedback_line,
    format_memory_search_line,
    format_dashboard_line,
    format_recommendations_line,
)
from memory_search.similarity_search import find_similar_setups
from memory_search.memory_summary    import build_memory_summary
from performance_intelligence.dashboard_builder  import build_dashboard
from performance_intelligence.dashboard_summary  import build_dashboard_summary
from recommendation_engine.recommendation_builder     import build_recommendations
from recommendation_engine.recommendation_summary     import build_recommendation_summary
from recommendation_engine.recommendation_persistence import save_recommendations

_EASTERN = pytz.timezone("America/New_York")
_DIV     = "=" * 60


# ── Confidence fusion rebuild ────────────────────────────────────────────────
# Mirrors _confidence_fusion() in discretionary_ai.py — used after patching
# a cached external AI result to keep fusion numbers consistent.

def _rebuild_fusion(snapshot: dict) -> dict:
    ai_conf    = snapshot.get("ai_discretionary", {}).get("ai_confidence", 0)
    mechanical = snapshot.get("qualification", {}).get("opportunity_score", 0)
    combined   = round((mechanical + ai_conf) / 2)
    diff       = abs(mechanical - ai_conf)
    if   diff <= 15: status = "agreement"
    elif diff <= 30: status = "mild_disagreement"
    else:            status = "strong_disagreement"
    return {
        "mechanical_score":    mechanical,
        "ai_confidence":       ai_conf,
        "combined_confidence": combined,
        "fusion_status":       status,
    }


# ── Per-scan compact console output ─────────────────────────────────────────

def _print_scan_summary(snapshot: dict, symbol: str, scan_num: int, saved_path: str | None):
    now_str = datetime.now(_EASTERN).strftime("%Y-%m-%d %H:%M:%S ET")

    qual = snapshot.get("qualification",  {})
    pb   = snapshot.get("playbook",       {})
    risk = snapshot.get("risk",           {})
    tb   = snapshot.get("toolbox",        {})
    ai   = snapshot.get("ai_discretionary", {})
    fus  = snapshot.get("confidence_fusion", {})

    preferred  = tb.get("preferred_tool") or "no_tool"
    candidates = tb.get("tool_candidates", [])
    pref_c     = next((c for c in candidates if c["tool"] == preferred), {})
    raw_tool   = (pref_c.get("raw_status")
                  or tb.get("best_available_raw_status") or "no_tool")
    eff_tool   = (pref_c.get("effective_status")
                  or tb.get("best_available_effective_status") or "no_tool")
    tp         = pref_c.get("trigger_prep", {})
    raw_trig   = tp.get("raw_trigger_status",      "n/a")
    eff_trig   = tp.get("effective_trigger_status", "n/a")

    ai_mode        = ai.get("ai_mode", "?")
    ai_model       = ai.get("model") or "internal"
    ai_conf        = ai.get("ai_confidence", 0)
    ai_reused      = ai.get("ai_reused", False)
    fallback       = ai.get("fallback_used", False)
    age_secs       = ai.get("ai_last_refresh_age_seconds")
    ai_ext_att     = ai.get("ai_external_attempted", False)
    ai_ext_ok      = ai.get("ai_external_success",   False)
    ai_err_type    = ai.get("ai_external_error_type")
    ai_model_used  = ai.get("ai_model_used") or ai_model
    ai_latency     = ai.get("latency_ms")

    mech     = fus.get("mechanical_score",    0)
    ai_c     = fus.get("ai_confidence",       0)
    combined = fus.get("combined_confidence", 0)
    fstatus  = fus.get("fusion_status",       "?")

    print(_DIV)
    print(f"LIVE SCAN {now_str} | {symbol} | scan #{scan_num}")
    print(_DIV)
    print(f"Qualification : {qual.get('status','?').upper()} ({qual.get('grade','?')}) score {qual.get('opportunity_score',0)}")

    pb_name = pb.get("selected_playbook", "no_playbook").upper()
    pb_stat = pb.get("status", "?").upper()
    print(f"Playbook      : {pb_name} / {pb.get('direction','?')} / {pb_stat}")

    risk_tier = risk.get("risk_tier", "?").upper()
    auth      = risk.get("authority_reason", "")
    print(f"Risk          : {risk_tier} -- {auth}")

    # Phase 5F.2 — regime constraint authority
    rp = snapshot.get("regime_permissions", {})
    if rp.get("enabled"):
        rp_status = (rp.get("permission_status") or "?").upper()
        rp_block  = rp.get("blocking_reasons") or []
        rp_tag    = f" | BLOCK: {rp_block[0]}" if rp_block else ""
        print(
            f"Regime Auth   : {rp_status}"
            f" | cap={rp.get('risk_multiplier_cap')}"
            f" | trigger>={rp.get('required_trigger_status')}"
            f" | min_age={rp.get('min_setup_age_scans')}"
            f" | profile={rp.get('management_profile')}{rp_tag}"
        )

    print(f"Tool          : {preferred}  raw={raw_tool.upper()}  eff={eff_tool.upper()}")

    trig_line = raw_trig.upper()
    if eff_trig.upper() != raw_trig.upper():
        trig_line += f" -> {eff_trig.upper()}"
    print(f"Trigger       : {trig_line}")

    if ai_reused:
        reuse_tag = f"reused=true ({age_secs}s ago)"
    else:
        reuse_tag = "reused=false"
    fallback_tag = " [fallback]" if fallback else ""
    print(f"AI            : {ai_mode} {ai_model}{fallback_tag} | confidence={ai_conf} | {reuse_tag}")

    if ai_ext_att:
        if ai_ext_ok:
            lat_str = f" | latency={ai_latency}ms" if ai_latency is not None else ""
            print(f"AI External   : SUCCESS | model={ai_model_used}{lat_str}")
        else:
            err_str = f" | reason={ai_err_type}" if ai_err_type else ""
            print(f"AI External   : FALLBACK | model={ai_model_used}{err_str}")

    print(f"Fusion        : mechanical={mech} / AI={ai_c} / combined={combined} / {fstatus.upper()}")

    st          = snapshot.get("state_transition", {})
    trans_label = st.get("transition", "stable").upper()
    prev_s      = st.get("previous_state", "none")
    cur_s       = st.get("current_state",  "no_trade")
    bars        = st.get("bars_in_state",  1)
    lifecycle   = st.get("setup_lifecycle", "dormant")
    warns       = st.get("warnings", [])
    trans_line  = f"{trans_label}  {prev_s} -> {cur_s}  [bars={bars}, lifecycle={lifecycle}]"
    if warns:
        trans_line += f"  WARN: {warns[0]}"
    print(f"Transition    : {trans_line}")

    deb     = snapshot.get("ai_debate", {})
    fv      = deb.get("final_verdict", {})
    db_bull = deb.get("bullish_thesis",  {}).get("case_strength", 0)
    db_bear = deb.get("bearish_thesis",  {}).get("case_strength", 0)
    db_neut = deb.get("neutral_thesis",  {}).get("case_strength", 0)
    db_stance = (fv.get("recommended_stance") or "stand_down").upper()
    db_dom    = (fv.get("dominant_thesis")     or "neutral").lower()
    if deb.get("enabled"):
        print(
            f"AI Debate     : bull={db_bull} bear={db_bear} neutral={db_neut}"
            f" -> {db_stance} ({db_dom} dominant)"
        )

    sl = snapshot.get("setup_lifecycle", {})
    if not sl.get("active"):
        print("Setup Life    : NONE")
    elif sl.get("invalidated"):
        print(
            f"Setup Life    : INVALIDATED | age={sl.get('age_scans',0)} scans"
            f" | reason={sl.get('reason','?')}"
        )
    else:
        q_path    = sl.get("quality_path", [])
        path_str  = "->".join(q_path[-5:]) if q_path else "?"
        sl_warns  = sl.get("warnings", [])
        warn_str  = f"  WARN: {sl_warns[0]}" if sl_warns else ""
        print(
            f"Setup Life    : ACTIVE | {sl.get('current_phase','?')}"
            f" | age={sl.get('age_scans',0)} scans"
            f" | highest={sl.get('highest_quality_reached','?')}"
            f" | current={sl.get('current_quality','?')}"
            f" | path={path_str}{warn_str}"
        )

    da = snapshot.get("decision_authority", {})
    da_decision = (da.get("decision") or "stand_down").upper()
    da_dir      = (da.get("direction") or "neutral").lower()
    da_conf     = da.get("confidence", 0)
    da_auth     = da.get("trade_authorized", False)
    da_reason   = da.get("reason", "")
    print(f"Decision      : {da_decision} | {da_dir} | confidence={da_conf} | trade_authorized={str(da_auth).lower()}")
    print(f"Reason        : {da_reason}")

    eg          = snapshot.get("execution_gate", {})
    eg_status   = (eg.get("gate_status") or "locked").upper()
    eg_allow    = eg.get("allow_execution", False)
    eg_would    = eg.get("would_authorize_if_enabled", False)
    print(
        f"Exec Gate     : {eg_status} | allow_execution={str(eg_allow).lower()}"
        f" | would_authorize={str(eg_would).lower()}"
    )

    ti         = snapshot.get("trade_intent", {})
    ti_type    = (ti.get("intent_type") or "none").upper()
    ti_created = ti.get("intent_created", False)
    ti_tool    = ti.get("preferred_tool") or "no_tool"
    ti_trig    = (ti.get("trigger_status") or "n/a").upper()
    ti_allow   = ti.get("execution_allowed", False)
    ti_reason  = ti.get("reason", "")
    ez         = ti.get("entry_zone") or {}
    zl         = ez.get("zone_low")
    zh         = ez.get("zone_high")
    if ti_created and zl is not None:
        zone_str = f" | zone {zl}-{zh}"
    else:
        zone_str = ""
    if ti_created:
        print(
            f"Trade Intent  : {ti_type} | {ti_tool}{zone_str}"
            f" | trigger {ti_trig} | exec_allowed={str(ti_allow).lower()}"
        )
    else:
        short_reason = ti_reason[:80] if ti_reason else "no active setup"
        print(f"Trade Intent  : {ti_type} | reason: {short_reason}")

    iscr        = snapshot.get("intent_score", {})
    isc_scored  = iscr.get("scored", False)
    raw_s       = iscr.get("raw_score",    0)
    raw_g       = iscr.get("raw_grade",    "F")
    raw_q       = iscr.get("raw_quality",  "no_intent")
    gated_s     = iscr.get("gated_score",  raw_s)
    gated_g     = iscr.get("gated_grade",  raw_g)
    gated_q     = iscr.get("gated_quality", raw_q)
    isc_applied = iscr.get("gating_applied", False)
    isc_reason  = iscr.get("gating_reason", "") if isc_applied else iscr.get("score_reason", "")
    if not isc_scored:
        short_sr = (iscr.get("score_reason", "no intent") or "no intent")[:80]
        print(f"Intent Score  : 0 / F / no_intent | reason: {short_sr}")
    elif isc_applied:
        print(
            f"Intent Score  : raw {raw_s}/{raw_g}/{raw_q}"
            f" -> gated {gated_s}/{gated_g}/{gated_q}"
            f" | reason: {isc_reason}"
        )
    else:
        print(f"Intent Score  : {raw_s} / {raw_g} / {raw_q} | no gating")

    ia         = snapshot.get("intent_archive", {})
    ia_id      = ia.get("active_intent_id")
    ia_status  = (ia.get("active_status") or "none").upper()
    ia_mfe     = ia.get("mfe", 0.0)
    ia_mae     = ia.get("mae", 0.0)
    ia_touched = ia.get("zone_touched", False)
    ia_bars    = ia.get("bars_active", 0)
    ia_new     = ia.get("new_record_created", False)
    ia_open    = ia.get("open_count", 0)
    ia_expired = ia.get("expired_this_scan", 0)
    if ia_id:
        short_id = ia_id[-15:] if len(ia_id) > 15 else ia_id
        new_tag     = " | NEW"     if ia_new     else ""
        expire_tag  = f" | expired={ia_expired}" if ia_expired else ""
        print(
            f"Intent Archive: {ia_status} | id=...{short_id}"
            f" | mfe={ia_mfe} | mae={ia_mae}"
            f" | touched={str(ia_touched).lower()} | age={ia_bars}"
            f"{new_tag}{expire_tag}"
        )
    elif ia_open > 0:
        print(f"Intent Archive: {ia_open} open record(s) (no primary)")
    else:
        print("Intent Archive: no active records")

    exp         = snapshot.get("experience_summary", {})
    exp_n       = exp.get("sample_size", 0)
    exp_wr      = exp.get("win_rate")
    exp_r       = exp.get("average_r")
    exp_matches = exp.get("historical_matches", 0)
    if exp_n == 0:
        print(f"Experience    : {exp_n} setup(s) | Insufficient Sample | AUTHORITY=OBSERVE_ONLY")
    elif exp_n < 20:
        match_tag = f" | {exp_matches} similar" if exp_matches else ""
        print(f"Experience    : {exp_n} setup(s) | Developing{match_tag} | AUTHORITY=OBSERVE_ONLY")
    else:
        parts = [f"{exp_n} setups"]
        if exp_wr is not None:
            parts.append(f"WR {exp_wr:.0f}%")
        if exp_r is not None:
            sign = "+" if exp_r >= 0 else ""
            parts.append(f"Avg {sign}{exp_r:.1f}R")
        if exp_matches:
            parts.append(f"{exp_matches} similar")
        print("Experience    : " + " | ".join(parts) + " | AUTHORITY=OBSERVE_ONLY")

    corr_rep  = snapshot.get("experience_correlation", {})
    corr_n    = corr_rep.get("sample_size", 0)
    corr_pos  = corr_rep.get("strongest_positive_correlations", [])
    corr_neg  = corr_rep.get("strongest_negative_correlations", [])
    if corr_n == 0 or (not corr_pos and not corr_neg):
        print("Exp Corr      : insufficient sample | AUTHORITY=OBSERVE_ONLY")
    else:
        c_parts = []
        if corr_pos:
            c_parts.append(f"+ {corr_pos[0]}")
        if corr_neg:
            c_parts.append(f"- {corr_neg[0]}")
        print("Exp Corr      : " + " | ".join(c_parts) + " | AUTHORITY=OBSERVE_ONLY")

    exp_link_line = format_experience_link_line(exp)
    if exp_link_line:
        print(exp_link_line)

    regime     = snapshot.get("market_regime", {})
    reg_label  = (regime.get("regime_label") or "unknown")
    reg_conf   = regime.get("confidence", 0)
    reg_vol    = (regime.get("volatility_state") or "unknown")
    reg_exp    = (regime.get("expansion_state")  or "unknown")
    if reg_label != "unknown":
        print(
            f"Regime        : {reg_label} | confidence={reg_conf}"
            f" | vol={reg_vol} | expansion={reg_exp} | OBSERVE_ONLY"
        )
    else:
        print("Regime        : unknown | insufficient evidence | OBSERVE_ONLY")

    fb     = snapshot.get("ai_feedback_summary") or {}
    fb_n   = fb.get("sample_size", 0)
    fb_hr  = fb.get("ai_helpful_rate")
    fb_awr = fb.get("agreement_win_rate")
    fb_dwr = fb.get("disagreement_win_rate")
    if fb_n == 0:
        print("AI Feedback   : 0 samples | insufficient | OBSERVE_ONLY")
    elif fb_hr is not None:
        parts = [f"{fb_n} samples", f"helpful {fb_hr:.0f}%"]
        if fb_awr is not None:
            parts.append(f"agreement WR {fb_awr:.0f}%")
        if fb_dwr is not None:
            parts.append(f"disagreement WR {fb_dwr:.0f}%")
        print("AI Feedback   : " + " | ".join(parts) + " | OBSERVE_ONLY")
    else:
        print(f"AI Feedback   : {fb_n} samples | developing | OBSERVE_ONLY")

    ms     = snapshot.get("memory_search") or {}
    ms_cnt = ms.get("match_count", 0)
    ms_cl  = ms.get("closed_match_count", 0)
    ms_wr  = ms.get("similar_win_rate")
    ms_ar  = ms.get("similar_average_r")
    ms_q   = ms.get("memory_quality", "none")
    if ms_cl == 0:
        print(f"Memory Search : no similar closed trades ({ms_cnt} raw matches) | {ms_q.upper()} | OBSERVE_ONLY")
    else:
        ms_parts = [f"{ms_cnt} matches", f"{ms_cl} closed"]
        if ms_wr is not None:
            ms_parts.append(f"WR {ms_wr:.1f}%")
        if ms_ar is not None:
            sign = "+" if ms_ar >= 0 else ""
            ms_parts.append(f"AvgR {sign}{ms_ar:.2f}")
        ms_parts.append(ms_q.upper())
        print("Memory Search : " + " | ".join(ms_parts) + " | OBSERVE_ONLY")

    dash   = snapshot.get("performance_dashboard") or {}
    d_n    = dash.get("sample_size", 0)
    d_wr   = dash.get("win_rate")
    d_ar   = dash.get("average_r")
    d_br   = dash.get("best_regime")
    d_qual = dash.get("performance_quality", "none")
    if d_n == 0:
        print(f"Dashboard     : insufficient sample | {d_qual.upper()} | OBSERVE_ONLY")
    else:
        d_parts = [f"{d_n} trades"]
        if d_wr is not None:
            d_parts.append(f"WR {d_wr:.1f}%")
        if d_ar is not None:
            sign = "+" if d_ar >= 0 else ""
            d_parts.append(f"AvgR {sign}{d_ar:.2f}")
        if d_br:
            d_parts.append(f"Best Regime {d_br}")
        d_parts.append(d_qual.upper())
        print("Dashboard     : " + " | ".join(d_parts) + " | OBSERVE_ONLY")

    rec      = snapshot.get("recommendations") or {}
    rec_cnt  = rec.get("recommendation_count", 0)
    rec_top  = rec.get("top_recommendation")
    rec_qual = rec.get("recommendation_quality", "none")
    if rec_cnt == 0:
        print(f"Recommend     : none | {rec_qual.upper()} | OBSERVE_ONLY")
    else:
        top_str = f" | top={rec_top[:55]}" if rec_top else ""
        print(f"Recommend     : {rec_cnt} active{top_str} | OBSERVE_ONLY")

    pa_plan   = snapshot.get("paper_activation_plan", {})
    pa        = snapshot.get("paper_activation", {})
    pa_status = (pa.get("status") or "disabled").upper()
    pa_reason = pa.get("reason", "")
    pa_symbol = pa_plan.get("symbol", symbol)
    pa_max_t  = pa_plan.get("max_trades", 1)
    pa_risk   = pa_plan.get("risk_dollars", 100)
    if pa_status == "ARMED":
        print(f"Paper Act     : ARMED | {pa_symbol} | max_trades={pa_max_t} | risk=${pa_risk:.0f}")
    elif pa_reason:
        print(f"Paper Act     : {pa_status} | {pa_reason[:80]}")
    else:
        print(f"Paper Act     : {pa_status}")

    pe        = snapshot.get("paper_execution", {})
    pe_status = (pe.get("status") or "disabled").upper()
    pe_reason = pe.get("reason", "")
    pe_order  = pe.get("order_summary", "")
    pe_id     = pe.get("alpaca_order_id")
    if pe_status == "SUBMITTED" and pe_order:
        id_tag = f" | order_id={pe_id}" if pe_id else ""
        print(f"Paper Exec    : {pe_status} | {pe_order}{id_tag}")
    elif pe_reason:
        short_reason = pe_reason[:80]
        print(f"Paper Exec    : {pe_status} | {short_reason}")
    else:
        print(f"Paper Exec    : {pe_status}")

    pm          = snapshot.get("position_monitor", {})
    pm_enabled  = pm.get("enabled", False)
    pm_status   = (pm.get("status") or "disabled").upper()
    pm_has_pos  = pm.get("has_open_position", False)
    if pm_enabled and pm_has_pos:
        pm_side = pm.get("side", "?")
        pm_qty  = pm.get("qty", 0)
        pm_cp   = pm.get("current_price")
        pm_sr   = pm.get("stop_reference")
        pm_sd   = pm.get("stop_distance")
        pm_pnl  = pm.get("unrealized_pnl")
        pm_exit = pm.get("exit_already_submitted", False)
        exit_tag = " | EXIT_SENT" if pm_exit else ""
        print(
            f"Pos Monitor   : {pm_status} | {pm_side} x{pm_qty}"
            f" @ {pm_cp} | stop={pm_sr} dist={pm_sd} | upnl={pm_pnl}{exit_tag}"
        )
    elif pm_enabled:
        pm_warns = pm.get("warnings", [])
        warn_str = f" | {pm_warns[0][:60]}" if pm_warns else ""
        print(f"Pos Monitor   : {pm_status}{warn_str}")
    else:
        print("Pos Monitor   : DISABLED")

    se          = snapshot.get("stop_enforcer", {})
    se_enabled  = se.get("enabled", False)
    se_action   = (se.get("action_taken") or "disabled").upper()
    se_breached = se.get("stop_breached", False)
    se_exit_id  = se.get("exit_order_id")
    se_warns    = se.get("warnings", [])
    if se_enabled:
        breach_tag = " | BREACHED" if se_breached else ""
        exit_tag   = f" | exit_id={se_exit_id}" if se_exit_id else ""
        warn_str   = f" | {se_warns[0][:60]}" if se_warns else ""
        print(f"Stop Enforcer : {se_action}{breach_tag}{exit_tag}{warn_str}")
    else:
        print("Stop Enforcer : DISABLED")

    bs          = snapshot.get("broker_stop", {})
    bs_enabled  = bs.get("enabled", False)
    bs_status   = (bs.get("status") or "disabled").upper()
    bs_price    = bs.get("stop_price")
    bs_id       = bs.get("stop_order_id")
    if not bs_enabled:
        print("Broker Stop   : DISABLED | BROKER_STOP_ENABLED=false")
    elif bs_status == "VERIFIED":
        print(f"Broker Stop   : VERIFIED | stop {bs_price} | order_id={bs_id}")
    elif bs_status == "SUBMITTED":
        print(f"Broker Stop   : SUBMITTED | stop {bs_price} | order_id={bs_id}")
    elif bs_status == "MISSING":
        print("Broker Stop   : MISSING | software stop backup active")
    else:
        print(f"Broker Stop   : {bs_status}")

    recon        = snapshot.get("trade_reconciliation", {})
    recon_status = recon.get("status", "no_active_trade")
    if recon_status == "closed":
        pnl = recon.get("realized_pnl")
        r   = recon.get("realized_r")
        hm  = recon.get("holding_minutes")
        pnl_str = f"{pnl:+.2f}" if pnl is not None else "unknown"
        r_str   = f" | R={r:.2f}" if r is not None else ""
        hm_str  = f" | {hm:.0f}min" if hm is not None else ""
        print(f"Trade Recon   : CLOSED | pnl={pnl_str}{r_str}{hm_str}")
    elif recon_status == "externally_closed":
        print("Trade Recon   : EXTERNALLY CLOSED | pnl=unknown")
    elif recon_status == "open":
        print("Trade Recon   : OPEN")
    elif recon_status in ("canceled", "cancelled", "rejected", "expired"):
        print(f"Trade Recon   : ENTRY {recon_status.upper()}")
    elif recon_status == "no_active_trade":
        print("Trade Recon   : NO ACTIVE TRADE")
    elif recon_status == "error":
        warns = recon.get("warnings", [])
        print(f"Trade Recon   : ERROR | {warns[0][:70] if warns else '?'}")
    else:
        print(f"Trade Recon   : {recon_status.upper()}")

    peo = snapshot.get("pending_entry_order") or {}
    peo_status = (peo.get("status") or "none").upper()
    peo_tid    = peo.get("trade_id")
    peo_oid    = peo.get("alpaca_order_id")
    peo_warns  = peo.get("warnings") or []
    if peo_status == "CANCELLED":
        tid_tag = f" | trade_id={peo_tid}" if peo_tid else ""
        print(f"Pending Entry : CANCELLED{tid_tag} | reason=setup_lifecycle_dead")
    elif peo_status == "NONE":
        print("Pending Entry : NONE")
    elif peo_status == "LIVE":
        os_before = peo.get("order_status_before") or "?"
        tid_tag   = f" | trade_id={peo_tid}" if peo_tid else ""
        print(f"Pending Entry : LIVE{tid_tag} | status={os_before}")
    elif peo_status == "CANCEL_FAILED":
        warn_str = f" | {peo_warns[0][:60]}" if peo_warns else ""
        print(f"Pending Entry : CANCEL_FAILED{warn_str}")
    elif peo_status == "ERROR":
        warn_str = f" | {peo_warns[0][:60]}" if peo_warns else ""
        print(f"Pending Entry : ERROR{warn_str}")
    else:
        print(f"Pending Entry : {peo_status}")

    orr         = snapshot.get("operational_readiness", {})
    orr_score   = orr.get("score", 0)
    orr_ready   = orr.get("ready", False)
    orr_issues  = orr.get("blocking_issues", [])
    orr_label   = "READY" if orr_ready else "NOT READY"
    issue_str   = f" | {orr_issues[0]}" if orr_issues else ""
    print(f"Readiness     : {orr_score}/100 | {orr_label}{issue_str}")

    ac          = snapshot.get("activation_controller", {})
    ac_status   = (ac.get("status") or "unknown").upper()
    ac_reason   = ac.get("reason", "")
    print(f"Activation    : {ac_status} | {ac_reason}")

    if saved_path:
        print(f"Saved         : {os.path.relpath(saved_path)}")

    print()


# ── End-of-loop summary ───────────────────────────────────────────────────────

def _print_loop_summary(
    scan_count: int,
    save_count: int,
    feed_errors: int,
    ai_ext_calls: int,
    ai_fallbacks: int,
    start_time: datetime,
):
    elapsed = int((datetime.now(_EASTERN) - start_time).total_seconds())
    mins, secs = divmod(elapsed, 60)

    print(_DIV)
    print("SCAN LOOP ENDED")
    print(_DIV)
    print(f"  Scans completed    : {scan_count}")
    print(f"  Snapshots saved    : {save_count}")
    print(f"  Feed errors        : {feed_errors}")
    print(f"  AI external calls  : {ai_ext_calls}")
    print(f"  AI fallbacks       : {ai_fallbacks}")
    print(f"  Elapsed time       : {mins}m {secs}s")
    print(_DIV)


# ── Main loop ────────────────────────────────────────────────────────────────

def run_scan_loop():
    symbol     = os.getenv("SCAN_SYMBOL",            "QQQ")
    lookback   = int(os.getenv("SCAN_LOOKBACK_BARS", "300"))
    start_t    = os.getenv("SCAN_START_TIME",        "08:30")
    end_t      = os.getenv("SCAN_END_TIME",          "15:00")
    interval   = int(os.getenv("SCAN_INTERVAL_SECONDS", "60"))
    max_iter   = int(os.getenv("MAX_SCAN_ITERATIONS",    "0"))
    ai_refresh = int(os.getenv("AI_REFRESH_SECONDS",     "60"))

    # AI refresh control only applies when the env mode calls external AI
    ai_env_mode        = os.getenv("AI_MODE", "internal").lower()
    use_refresh_ctrl   = ai_env_mode in ("external", "hybrid")

    memory     = MarketMemory(max_snapshots=20)
    ai_ctrl    = AIRefreshController(ai_refresh)

    scan_count   = 0
    save_count   = 0
    feed_errors  = 0
    ai_ext_calls = 0
    ai_fallbacks = 0
    start_time   = datetime.now(_EASTERN)

    previous_snapshot        = None
    previous_qual_state      = None
    bars_in_state            = 0
    setup_tracker            = SetupTracker()
    prev_experience_summary  = None   # Phase 3A: carry forward for AI input next scan
    # Phase 5E.3: carry 5C/5D/5E summaries forward so AI sees them on the next scan
    prev_memory_search       = None
    prev_dashboard           = None
    prev_recommendations     = None

    # Initialise provider (fail fast before entering the loop)
    try:
        provider = get_provider()
    except DataFeedError as exc:
        print(f"[SCAN LOOP ERROR] Cannot initialise data provider: {exc}")
        return

    print(_DIV)
    print(f"Phase 1P - Live Scan Loop | {symbol}")
    print(_DIV)
    limit_str = "unlimited" if max_iter == 0 else str(max_iter)
    print(f"  Interval     : {interval}s | Max iterations : {limit_str}")
    print(f"  Scan window  : {start_t} - {end_t} ET")
    if use_refresh_ctrl:
        print(f"  AI refresh   : every {ai_refresh}s + signal-triggered on high-confidence setups")
    else:
        print(f"  AI mode      : {ai_env_mode} (runs every scan)")
    print("  Press Ctrl+C to stop")
    print()

    try:
        while True:
            scan_count += 1
            if max_iter > 0 and scan_count > max_iter:
                scan_count -= 1
                break

            scan_start = time.monotonic()

            # ── Scan window guard ─────────────────────────────────────────
            if not is_within_scan_window(start_t, end_t):
                now_str = datetime.now(_EASTERN).strftime("%H:%M ET")
                print(f"  [{now_str}] Outside scan window ({start_t}-{end_t} ET) -- waiting {interval}s ...")
                time.sleep(interval)
                continue

            # ── Fetch live data ───────────────────────────────────────────
            try:
                candles_1m = provider.fetch_1m_candles(symbol, lookback)
            except DataFeedError as exc:
                feed_errors += 1
                print(f"  [FEED ERROR scan #{scan_count}] {exc}")
                _sleep_remainder(scan_start, interval)
                continue

            if not candles_1m:
                feed_errors += 1
                print(f"  [FEED ERROR scan #{scan_count}] No candles returned for {symbol}.")
                _sleep_remainder(scan_start, interval)
                continue

            raw_data = build_timeframes(candles_1m)

            # ── Decide AI mode for this iteration ─────────────────────────
            if use_refresh_ctrl:
                refresh_ai    = ai_ctrl.should_refresh()
                mode_override = None if refresh_ai else "internal"
            else:
                refresh_ai    = True
                mode_override = None   # honour AI_MODE env var directly

            # ── Build snapshot ─────────────────────────────────────────────
            try:
                snapshot = build_snapshot(
                    raw_data,
                    memory=memory,
                    ai_mode_override=mode_override,
                    experience_summary=prev_experience_summary,
                    prior_memory_search=prev_memory_search,
                    prior_dashboard=prev_dashboard,
                    prior_recommendations=prev_recommendations,
                )
            except Exception as exc:
                print(f"  [SNAPSHOT ERROR scan #{scan_count}] {exc}")
                _sleep_remainder(scan_start, interval)
                continue

            # ── AI result handling ─────────────────────────────────────────
            ai_disc = snapshot.get("ai_discretionary", {})

            if use_refresh_ctrl and not refresh_ai and ai_ctrl.has_cached_result:
                # Inject cached external result and recompute fusion
                snapshot["ai_discretionary"] = ai_ctrl.get_reused()
                snapshot["confidence_fusion"] = _rebuild_fusion(snapshot)
            elif use_refresh_ctrl and refresh_ai:
                # External was attempted — check outcome
                if ai_disc.get("external_ai_connected") and not ai_disc.get("fallback_used"):
                    ai_ctrl.record_refresh(ai_disc)
                    ai_ext_calls += 1
                elif ai_disc.get("ai_mode") in ("external", "hybrid") and ai_disc.get("fallback_used"):
                    ai_fallbacks += 1

            # Ensure ai_reused field is always present
            if "ai_reused" not in snapshot.get("ai_discretionary", {}):
                snapshot["ai_discretionary"]["ai_reused"] = False

            # Update controller state for next iteration's refresh decision
            if use_refresh_ctrl:
                ai_ctrl.update_state(snapshot)

            # ── State transition detection ─────────────────────────────────
            cur_qual = (snapshot.get("qualification", {}).get("status") or "no_trade").lower()
            if cur_qual == previous_qual_state:
                bars_in_state += 1
            else:
                bars_in_state = 1
            snapshot["state_transition"] = analyze_transition(
                snapshot, previous_snapshot, bars_in_state
            )
            previous_snapshot   = snapshot
            previous_qual_state = cur_qual

            # ── Setup lifecycle tracking ───────────────────────────────────
            snapshot["setup_lifecycle"] = setup_tracker.update(snapshot, symbol)

            # ── Decision Authority ─────────────────────────────────────────
            snapshot["decision_authority"] = make_decision(snapshot)
            da_line = format_decision_line(snapshot["decision_authority"])
            if da_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + da_line
                ).strip()

            # ── Execution Gate (Phase 1U) ──────────────────────────────────
            snapshot["execution_gate"] = evaluate_gate(snapshot)
            gate_line = format_gate_line(snapshot["execution_gate"])
            if gate_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + gate_line
                ).strip()

            # ── Trade Intent (Phase 1V) ────────────────────────────────────
            snapshot["trade_intent"] = build_intent(snapshot, symbol)
            intent_line = format_intent_line(snapshot["trade_intent"])
            if intent_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + intent_line
                ).strip()

            # ── Intent Score (Phase 1W) ────────────────────────────────────
            snapshot["intent_score"] = score_intent(snapshot, symbol)
            score_line = format_score_line(snapshot["intent_score"])
            if score_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + score_line
                ).strip()

            # ── Intent Archive (Phase 1X) ──────────────────────────────────
            snapshot["intent_archive"] = update_archive(snapshot, symbol)
            archive_line = format_archive_line(snapshot["intent_archive"])
            if archive_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + archive_line
                ).strip()

            # ── Experience Intelligence (Phase 3A — OBSERVE_ONLY) ─────────
            snapshot["experience_summary"] = build_experience_summary(snapshot, symbol)
            snapshot["experience_report"]  = build_experience_report(
                snapshot["experience_summary"]
            )
            # Phase 5B: expose AI feedback summary as top-level snapshot key
            snapshot["ai_feedback_summary"] = (
                snapshot["experience_summary"].get("ai_feedback_summary") or {}
            )
            prev_experience_summary = snapshot["experience_summary"]
            exp_line = format_experience_line(snapshot["experience_summary"])
            if exp_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + exp_line
                ).strip()

            # ── Experience Correlation (Phase 3B — OBSERVE_ONLY) ──────────
            _raw_corr = build_correlation_for_symbol(symbol)
            snapshot["experience_correlation"] = build_correlation_report(_raw_corr)
            corr_line = format_correlation_line(snapshot["experience_correlation"])
            if corr_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + corr_line
                ).strip()

            # ── Experience Linkage (Phase 3C — OBSERVE_ONLY) ──────────────
            link_line = format_experience_link_line(snapshot["experience_summary"])
            if link_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + link_line
                ).strip()

            # ── Memory Similarity Search (Phase 5C — OBSERVE_ONLY) ────────
            _ms_result = find_similar_setups(snapshot, symbol)
            snapshot["memory_search"] = build_memory_summary(_ms_result)
            snapshot["memory_search"]["_full_result"] = _ms_result
            # Phase 5E.3: persist summary (no large objects) for next scan's AI input
            prev_memory_search = {k: v for k, v in snapshot["memory_search"].items() if k != "_full_result"}
            ms_line = format_memory_search_line(snapshot["memory_search"])
            if ms_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + ms_line
                ).strip()

            # ── Performance Intelligence Dashboard (Phase 5D — OBSERVE_ONLY) ─
            _dash_full = build_dashboard(
                symbol,
                memory_summary=snapshot.get("memory_search"),
            )
            snapshot["performance_dashboard"] = build_dashboard_summary(_dash_full)
            snapshot["performance_dashboard"]["_full_dashboard"] = _dash_full
            # Phase 5E.3: persist summary (no large objects) for next scan's AI input
            prev_dashboard = {k: v for k, v in snapshot["performance_dashboard"].items() if k != "_full_dashboard"}
            dash_line = format_dashboard_line(snapshot["performance_dashboard"])
            if dash_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + dash_line
                ).strip()

            # ── Recommendation Engine (Phase 5E — OBSERVE_ONLY) ────────────
            # Pass _dash_full explicitly to avoid a redundant disk read inside builder
            _rec_full = build_recommendations(symbol, snapshot, dashboard=_dash_full)
            snapshot["recommendations"] = build_recommendation_summary(_rec_full)
            snapshot["recommendations"]["_full_result"] = _rec_full
            # Phase 5E.3: persist summary (no large objects) for next scan's AI input
            prev_recommendations = {k: v for k, v in snapshot["recommendations"].items() if k != "_full_result"}
            rec_line = format_recommendations_line(snapshot["recommendations"])
            if rec_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + rec_line
                ).strip()

            # ── Recommendation Persistence (Phase 5E.1) ────────────────────
            save_recommendations(symbol, _rec_full)

            # ── Position Monitor (Phase 2B — moved up) ────────────────────
            snapshot["position_monitor"] = monitor_paper_position(snapshot, symbol)
            pm_line = format_position_monitor_line(snapshot["position_monitor"])
            if pm_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + pm_line
                ).strip()

            # ── Broker Stop (Phase 4B) ─────────────────────────────────────
            snapshot["broker_stop"] = snapshot["position_monitor"].get(
                "broker_stop", {"enabled": False, "status": "disabled"}
            )
            bs_line = format_broker_stop_line(snapshot["broker_stop"])
            if bs_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + bs_line
                ).strip()

            # ── Operational Readiness (Phase 2C) ──────────────────────────
            snapshot["operational_readiness"] = run_readiness_check(snapshot)
            orr_line = format_operational_readiness_line(snapshot["operational_readiness"])
            if orr_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + orr_line
                ).strip()

            snapshot["activation_controller"] = determine_activation(
                snapshot["operational_readiness"]
            )
            ac_line = format_activation_line(snapshot["activation_controller"])
            if ac_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + ac_line
                ).strip()

            # ── Paper Activation Plan (Phase 2D) ──────────────────────────
            snapshot["paper_activation_plan"] = build_activation_plan(snapshot, symbol)
            snapshot["paper_activation"]      = run_activation(
                snapshot["paper_activation_plan"], symbol
            )
            pa_line = format_paper_activation_line(snapshot["paper_activation"])
            if pa_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + pa_line
                ).strip()
            log_activation_event(
                snapshot["paper_activation_plan"],
                snapshot["paper_activation"],
                symbol,
            )

            # ── Paper Execution (Phase 2A — gated by activation) ──────────
            if snapshot["paper_activation"].get("allow_order_attempts"):
                snapshot["paper_execution"] = attempt_paper_execution(snapshot, symbol)
            else:
                snapshot["paper_execution"] = {
                    "status":          "disabled",
                    "reason":          f"activation gated: {snapshot['paper_activation'].get('reason', 'not armed')}",
                    "order_summary":   None,
                    "alpaca_order_id": None,
                    "trade_id":        None,
                }
            pe_line = format_paper_execution_line(snapshot["paper_execution"])
            if pe_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + pe_line
                ).strip()

            # ── Stop Enforcer (Phase 2B) ───────────────────────────────────
            snapshot["stop_enforcer"] = enforce_stop(
                snapshot, symbol, snapshot["position_monitor"]
            )
            se_line = format_stop_enforcer_line(snapshot["stop_enforcer"])
            if se_line:
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + se_line
                ).strip()

            # ── Trade Reconciliation (Phase 4A) ───────────────────────────
            snapshot["trade_reconciliation"] = reconcile_trade(symbol)
            recon = snapshot["trade_reconciliation"]
            if recon.get("status") == "closed":
                pnl = recon.get("realized_pnl")
                r   = recon.get("realized_r")
                pnl_str = f"{pnl:+.2f}" if pnl is not None else "unknown"
                r_str   = f" R={r:.2f}" if r is not None else ""
                recon_ai_line = f"Trade closed: pnl={pnl_str}{r_str}"
                snapshot["ai_context"]["summary"] = (
                    snapshot["ai_context"].get("summary", "") + " " + recon_ai_line
                ).strip()

            # ── Trade Management (Phase 5E.8) ─────────────────────────────
            snapshot["trade_management"] = manage_open_trade(snapshot, symbol)
            tm = snapshot["trade_management"]
            if tm.get("action") not in ("none", "no_trade", "hold"):
                print(
                    f"  Trade Mgmt   : {tm.get('action')} | {tm.get('details', tm.get('reason', ''))}"
                )

            # ── Pending Entry Order Lifecycle (Phase 5E.5) ────────────────
            snapshot["pending_entry_order"] = cancel_pending_entry_order_if_setup_dead(
                snapshot, symbol
            )

            # ── Persist snapshot ───────────────────────────────────────────
            saved_path = None
            try:
                saved_path = save_snapshot(snapshot, symbol)
                save_count += 1
            except Exception as exc:
                print(f"  [SAVE WARNING scan #{scan_count}] {exc}")

            # ── Print compact summary ─────────────────────────────────────
            _print_scan_summary(snapshot, symbol, scan_count, saved_path)

            _sleep_remainder(scan_start, interval)

    except KeyboardInterrupt:
        pass

    _print_loop_summary(
        scan_count, save_count, feed_errors,
        ai_ext_calls, ai_fallbacks, start_time,
    )


def _sleep_remainder(scan_start: float, interval: int):
    """Sleep for whatever is left of the scan interval."""
    remaining = interval - (time.monotonic() - scan_start)
    if remaining > 0:
        time.sleep(remaining)
