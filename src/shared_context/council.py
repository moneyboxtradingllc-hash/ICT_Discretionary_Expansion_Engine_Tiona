"""
Phase 5G.2/5G.3 — Council of Specialists.
Phase FC-1   — Council veto authority (June 11 promotion).

Each major subsystem becomes a council member. Every member reads the SAME
SharedMarketContext and returns an opinion:

    {"member": ..., "vote": "yes"|"no"|"neutral", "confidence": 0-100,
     "reasons": [...], "concerns": [...]}

AUTHORITY (FC-1):
  COUNCIL_AUTHORITY=observe_only (default) — 5G behavior: microphones only.
  COUNCIL_AUTHORITY=enforce — the veto becomes a blocking input to the
  execution gate. June 11 evidence: REGIME voted NO at 95 and DELIVERY NO at
  75 on a trade that resolved -1.34R; neither vote had a wire to the gate.

  The veto is COMPUTED on every run (observability); it is ENFORCED only by
  the execution gate, and only when authority_level == "enforce".
  Rollback: COUNCIL_AUTHORITY=observe_only.

Veto triggers (either):
  - >= COUNCIL_VETO_MIN_NO_VOTES members vote NO at confidence >=
    COUNCIL_VETO_MIN_CONFIDENCE   (June 11: 2 members, 95 and 75)
  - consensus dominant position is NO at confidence >= the same threshold
"""
import os

_AUTHORITY = "observe_only"


def _authority() -> str:
    level = os.getenv("COUNCIL_AUTHORITY", _AUTHORITY).lower().strip()
    return level if level in ("observe_only", "enforce") else _AUTHORITY


def _veto_min_no_votes() -> int:
    try:
        return max(1, int(os.getenv("COUNCIL_VETO_MIN_NO_VOTES", "2")))
    except (TypeError, ValueError):
        return 2


def _veto_min_confidence() -> int:
    try:
        return max(0, min(100, int(os.getenv("COUNCIL_VETO_MIN_CONFIDENCE", "70"))))
    except (TypeError, ValueError):
        return 70

_TREND_REGIMES        = frozenset({"trend_up", "trend_down", "expansion_up", "expansion_down"})
_ROTATIONAL_REGIMES   = frozenset({"range_rotation", "chop"})
_UNHEALTHY_VOL        = frozenset({"unstable", "toxic", "explosive", "extreme", "high"})
_CONTINUATION_PLAYBOOKS = frozenset({
    "trend_continuation", "opening_drive", "range_expansion",
    "manipulation_to_distribution",
})
_REVERSAL_PLAYBOOKS = frozenset({
    "liquidity_sweep_reversal", "failed_breakout_reversal",
})


def _opinion(member, vote, confidence, reasons, concerns):
    return {
        "member":     member,
        "vote":       vote,
        "confidence": max(0, min(100, int(confidence))),
        "reasons":    reasons[:4],
        "concerns":   concerns[:4],
    }


# ── Council members ───────────────────────────────────────────────────────────

def regime_opinion(ctx: dict) -> dict:
    """REGIME — is the environment itself tradeable?"""
    regime   = ctx.get("regime", "unknown")
    vol      = ctx.get("volatility_state", "unknown")
    reasons, concerns = [], []
    problems = 0

    if regime in _ROTATIONAL_REGIMES:
        problems += 1
        concerns.append(f"regime is {regime} — rotational environment")
    if regime == "high_volatility":
        problems += 1
        concerns.append("high volatility regime — disorderly conditions")
    if ctx.get("exhaustion_present"):
        problems += 1
        concerns.append("exhaustion risk present — move may be late")
    if vol in _UNHEALTHY_VOL:
        problems += 1
        concerns.append(f"volatility state {vol}")

    if problems == 0 and regime in _TREND_REGIMES:
        reasons.append(f"regime {regime} with healthy conditions")
        return _opinion("REGIME", "yes",
                        max(55, ctx.get("regime_confidence", 0)), reasons, concerns)

    if problems >= 1:
        reasons.append(f"I see {regime}"
                       + (" and exhaustion_risk" if ctx.get("exhaustion_present") else ""))
        return _opinion("REGIME", "no", min(95, 55 + 15 * problems), reasons, concerns)

    reasons.append(f"regime {regime} — no strong signal either way")
    return _opinion("REGIME", "neutral", 50, reasons, concerns)


def delivery_opinion(ctx: dict) -> dict:
    """DELIVERY — is price being delivered with intent in one direction?"""
    conf   = ctx.get("delivery_confidence", 0)
    intact = ctx.get("continuation_intact", False)
    state  = ctx.get("delivery_state", "unknown")
    reasons, concerns = [], []

    if intact and conf >= 60:
        reasons.append(f"delivery intact: {state} (confidence {conf})")
        return _opinion("DELIVERY", "yes", conf, reasons, concerns)

    if not intact or conf < 40:
        reasons.append("continuation weakened" if state != "unknown"
                       else "no observable delivery")
        concerns.append(f"delivery state {state} at confidence {conf}")
        return _opinion("DELIVERY", "no", max(55, 100 - conf), reasons, concerns)

    reasons.append(f"delivery {state} forming but unconfirmed")
    return _opinion("DELIVERY", "neutral", 50, reasons, concerns)


def opportunity_opinion(ctx: dict) -> dict:
    """OPPORTUNITY — is there a classified opportunity that fits the environment?"""
    pb     = ctx.get("playbook", "no_playbook")
    regime = ctx.get("regime", "unknown")
    reasons, concerns = [], []

    if pb in ("no_playbook", ""):
        reasons.append("no tactical opportunity classified")
        return _opinion("OPPORTUNITY", "no", 80, reasons, concerns)

    if pb in _CONTINUATION_PLAYBOOKS and regime in _ROTATIONAL_REGIMES:
        reasons.append(f"continuation playbook '{pb}' inside {regime}")
        concerns.append("playbook fights the regime")
        return _opinion("OPPORTUNITY", "no", 75, reasons, concerns)

    if pb in _REVERSAL_PLAYBOOKS:
        if ctx.get("reversal_present"):
            reasons.append(f"reversal playbook '{pb}' with reversal evidence present")
            return _opinion("OPPORTUNITY", "yes", 70, reasons, concerns)
        reasons.append(f"reversal playbook '{pb}' without confirmed reversal evidence")
        concerns.append("no sweep+reclaim or MSS observed in context")
        return _opinion("OPPORTUNITY", "neutral", 50, reasons, concerns)

    if pb in _CONTINUATION_PLAYBOOKS and regime in _TREND_REGIMES:
        reasons.append(f"continuation playbook '{pb}' aligned with {regime}")
        return _opinion("OPPORTUNITY", "yes", 70, reasons, concerns)

    reasons.append(f"playbook '{pb}' present — fit to {regime} unclear")
    return _opinion("OPPORTUNITY", "neutral", 50, reasons, concerns)


def qualification_opinion(ctx: dict) -> dict:
    """QUALIFICATION — how good does the setup itself look?"""
    status = ctx.get("qualification_status", "no_trade")
    score  = ctx.get("qualification_score", 0)
    reasons, concerns = [], []

    if status in ("elite", "qualified"):
        reasons.append(f"qualification {status} at score {score}")
        if ctx.get("setup_age", 0) <= 1:
            concerns.append("setup is newborn (age <= 1 scan)")
        return _opinion("QUALIFICATION", "yes", score, reasons, concerns)

    if status == "no_trade":
        reasons.append("qualification sees no opportunity")
        return _opinion("QUALIFICATION", "no", 90, reasons, concerns)

    reasons.append(f"qualification {status} at score {score} — not yet convincing")
    return _opinion("QUALIFICATION", "neutral", max(40, score), reasons, concerns)


def toolbox_opinion(ctx: dict) -> dict:
    """TOOLBOX — is there a usable entry tool with a live trigger?"""
    tool    = ctx.get("toolbox_tool", "no_tool")
    trigger = ctx.get("trigger_status", "n/a")
    reasons, concerns = [], []

    if tool in ("no_tool", ""):
        reasons.append("no entry tool available")
        return _opinion("TOOLBOX", "no", 80, reasons, concerns)

    if trigger == "confirmed":
        reasons.append(f"high quality {tool} with confirmed trigger")
        return _opinion("TOOLBOX", "yes", 85, reasons, concerns)

    if trigger == "confirmation_needed":
        reasons.append(f"{tool} in zone — awaiting confirmation")
        concerns.append("trigger not yet confirmed")
        return _opinion("TOOLBOX", "yes", 65, reasons, concerns)

    if trigger in ("waiting_for_retest", "retest_in_progress"):
        reasons.append(f"{tool} waiting for retest")
        return _opinion("TOOLBOX", "neutral", 50, reasons, concerns)

    reasons.append(f"{tool} trigger is {trigger}")
    return _opinion("TOOLBOX", "no", 75, reasons, concerns)


def risk_opinion(ctx: dict) -> dict:
    """RISK — how much capital does the environment deserve?"""
    mult = ctx.get("risk_multiplier", 1.0)
    reasons, concerns = [], []

    if mult <= 0:
        reasons.append("risk governor blocked — no capital authorized")
        return _opinion("RISK", "no", 90, reasons, concerns)

    if mult < 1.0:
        reasons.append(f"{mult}x maximum risk")
        if mult <= 0.5:
            concerns.append(f"risk capped at {mult}x — environment penalized")
        return _opinion("RISK", "neutral", 60, reasons, concerns)

    reasons.append("full risk available — no environmental penalties")
    return _opinion("RISK", "yes", 70, reasons, concerns)


_MEMBERS = (
    regime_opinion,
    delivery_opinion,
    opportunity_opinion,
    qualification_opinion,
    toolbox_opinion,
    risk_opinion,
)


# ── 5G.3 — Council report ─────────────────────────────────────────────────────

def generate_council_report(opinions: list) -> dict:
    """
    Aggregate member opinions into a consensus report.
    OBSERVE ONLY — never blocks, never raises.
    """
    try:
        yes     = [o for o in opinions if o.get("vote") == "yes"]
        no      = [o for o in opinions if o.get("vote") == "no"]
        neutral = [o for o in opinions if o.get("vote") == "neutral"]
        decided = yes + no

        if not decided:
            dominant   = "neutral"
            strength   = 50
            confidence = round(sum(o["confidence"] for o in neutral) / len(neutral)) if neutral else 0
        elif len(yes) > len(no):
            dominant   = "yes"
            strength   = round(100 * len(yes) / len(decided))
            confidence = round(sum(o["confidence"] for o in yes) / len(yes))
        elif len(no) > len(yes):
            dominant   = "no"
            strength   = round(100 * len(no) / len(decided))
            confidence = round(sum(o["confidence"] for o in no) / len(no))
        else:
            dominant   = "divided"
            strength   = 50
            confidence = round(sum(o["confidence"] for o in decided) / len(decided))

        concerns, seen = [], set()
        for o in opinions:
            for c in o.get("concerns", []):
                if c not in seen:
                    seen.add(c)
                    concerns.append(c)

        return {
            "yes_votes":          len(yes),
            "no_votes":           len(no),
            "neutral_votes":      len(neutral),
            "dominant_position":  dominant,
            "confidence":         confidence,
            "critical_concerns":  concerns[:6],
            "consensus_strength": strength,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "yes_votes": 0, "no_votes": 0, "neutral_votes": 0,
            "dominant_position": "error", "confidence": 0,
            "critical_concerns": [f"council report error: {exc}"],
            "consensus_strength": 0,
        }


def evaluate_veto(members: list, report: dict) -> dict:
    """
    Phase FC-1 — compute the council veto. Always computed (observability);
    only the execution gate enforces it, and only under
    COUNCIL_AUTHORITY=enforce. Never raises.
    """
    try:
        min_conf  = _veto_min_confidence()
        strong_no = [
            {"member": m.get("member"), "confidence": m.get("confidence", 0)}
            for m in (members or [])
            if m.get("vote") == "no" and m.get("confidence", 0) >= min_conf
        ]
        consensus_no = (
            (report or {}).get("dominant_position") == "no"
            and (report or {}).get("confidence", 0) >= min_conf
        )
        triggered = len(strong_no) >= _veto_min_no_votes() or consensus_no

        if triggered:
            names = ", ".join(
                f"{m['member']}@{m['confidence']}" for m in strong_no
            ) or "consensus NO"
            reason = f"council veto: high-confidence NO from {names}"
        else:
            reason = ""

        return {
            "veto_triggered":  triggered,
            "strong_no_votes": strong_no,
            "consensus_no":    consensus_no,
            "veto_reason":     reason,
            "min_no_votes":    _veto_min_no_votes(),
            "min_confidence":  min_conf,
        }
    except Exception as exc:  # noqa: BLE001
        # Veto computation failure must never block (fail-open).
        return {
            "veto_triggered":  False,
            "strong_no_votes": [],
            "consensus_no":    False,
            "veto_reason":     f"veto evaluation error (fail-open): {exc}",
            "min_no_votes":    2,
            "min_confidence":  70,
        }


def run_council(ctx: dict) -> dict:
    """
    Phase 5G — Convene the council on a SharedMarketContext.
    Phase FC-1 — veto computed every run; enforced only by the gate under
    COUNCIL_AUTHORITY=enforce. Never raises.
    """
    members = []
    for member_fn in _MEMBERS:
        try:
            members.append(member_fn(ctx or {}))
        except Exception as exc:  # noqa: BLE001
            members.append(_opinion(
                member_fn.__name__.replace("_opinion", "").upper(),
                "neutral", 0, [], [f"member error: {exc}"],
            ))

    report = generate_council_report(members)

    return {
        "enabled":         True,
        "authority_level": _authority(),
        "members":         members,
        "report":          report,
        "veto":            evaluate_veto(members, report),
    }
