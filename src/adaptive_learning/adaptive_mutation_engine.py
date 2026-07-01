"""
Adaptive Learning — Phase 4: Bounded Mutation Engine (SHADOW MODE).

The FIRST authority-bearing adaptive layer — but strictly bounded and, this
phase, SHADOW only. It consumes the DEFENSIVE_ONLY policy report and computes
the mutations it WOULD apply to a live candidate. The mutation is computed,
visible, and logged; it is NOT executed. execution_engine still reads the
original authority. ADAPTIVE-5 turns this live.

CONSTITUTION — DEFENSIVE_ONLY. The engine may ONLY:
  * reduce confidence (-10%)          when confidence_penalty_recommended
  * reduce size (halve, floor, min 1) when risk_reduction_recommended
  * raise a soft veto (trade_blocked) when trade_block_recommended

It may NEVER: create a trade / direction / playbook / tool / qualification;
override ECU thesis / market commander / risk governor; increase size or
confidence; modify stops or targets. Boost recommendations are IGNORED this
phase. The input candidate is treated as read-only (never mutated in place).
Never raises.
"""
from __future__ import annotations

CONFIDENCE_PENALTY_FACTOR = 0.90   # RULE 1 — reduce confidence by 10%
RISK_REDUCTION_FACTOR     = 0.50   # RULE 2 — halve size
MIN_QTY                   = 1      # RULE 2 — size floor

AUTHORITY_LEVEL = "shadow"          # HARD-LOCK — computed, not executed this phase
POSTURE         = "DEFENSIVE_ONLY"  # HARD-LOCK


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def mutate_candidate(candidate: dict, adaptive_policy: dict) -> dict:
    """Compute the DEFENSIVE_ONLY shadow mutation for a candidate given the policy
    report. Returns the mutation record (see module docstring). Never raises and
    never mutates `candidate` in place."""
    try:
        c = candidate or {}
        p = adaptive_policy or {}

        orig_conf = c.get("confidence")
        orig_qty  = c.get("qty")
        new_conf  = orig_conf
        new_qty   = orig_qty

        penalty        = bool(p.get("confidence_penalty_recommended"))
        risk_reduction = bool(p.get("risk_reduction_recommended"))
        block          = bool(p.get("trade_block_recommended"))
        boost          = bool(p.get("confidence_boost_recommended"))

        types: list = []
        reasoning: list = []
        blocked = False

        # ── RULE 1 — confidence penalty (-10%) ──────────────────────────────
        if penalty and _is_num(orig_conf):
            new_conf = round(float(orig_conf) * CONFIDENCE_PENALTY_FACTOR, 6)
            types.append("confidence_penalty")
            reasoning.append(
                f"confidence_penalty: confidence {orig_conf} -> {new_conf} (-10%)")

        # ── RULE 2 — risk reduction (halve, floor toward zero, never below 1) ─
        if risk_reduction and _is_num(orig_qty) and orig_qty > 0:
            reduced = int(float(orig_qty) * RISK_REDUCTION_FACTOR)   # floor
            new_qty = max(MIN_QTY, reduced)
            types.append("risk_reduction")
            reasoning.append(
                f"risk_reduction: qty {orig_qty} -> {new_qty} (halved, min {MIN_QTY})")

        # ── RULE 3 — trade block (soft adaptive veto) ───────────────────────
        if block:
            blocked = True
            types.append("trade_block")
            reasoning.append("trade_block: soft adaptive veto (shadow — not enforced)")

        # ── RULE 4 — boosts are IGNORED (ADAPTIVE-4 is DEFENSIVE_ONLY) ───────
        if boost:
            reasoning.append(
                "confidence_boost recommended but IGNORED — upward mutation not "
                "permitted until a later phase (DEFENSIVE_ONLY)")

        conf_changed = _is_num(orig_conf) and new_conf != orig_conf
        qty_changed  = new_qty != orig_qty
        mutated = bool(conf_changed or qty_changed or blocked)

        # read-only: build a copy carrying only the defensive changes
        mutated_candidate = dict(c)
        if conf_changed:
            mutated_candidate["confidence"] = new_conf
        if qty_changed:
            mutated_candidate["qty"] = new_qty
        mutated_candidate["trade_blocked"] = blocked

        return {
            "mutated":              mutated,
            "mutation_type":        "+".join(types) if types else "none",
            "mutation_types":       types,
            "original_confidence":  orig_conf,
            "new_confidence":       new_conf,
            "original_qty":         orig_qty,
            "new_qty":              new_qty,
            "trade_blocked":        blocked,
            "mutation_reasoning":   reasoning,
            "mutated_candidate":    mutated_candidate,
            "authority_level":      AUTHORITY_LEVEL,   # SHADOW
            "posture":              POSTURE,
        }
    except Exception as exc:  # noqa: BLE001
        return _neutral(candidate, reason=f"mutation_error:{type(exc).__name__}")


def _neutral(candidate: dict, reason: str = "no mutation") -> dict:
    """Safe no-op mutation record preserving the original candidate."""
    c = candidate or {}
    return {
        "mutated":             False,
        "mutation_type":       "none",
        "mutation_types":      [],
        "original_confidence": c.get("confidence"),
        "new_confidence":      c.get("confidence"),
        "original_qty":        c.get("qty"),
        "new_qty":             c.get("qty"),
        "trade_blocked":       False,
        "mutation_reasoning":  [reason],
        "mutated_candidate":   dict(c),
        "authority_level":     AUTHORITY_LEVEL,
        "posture":             POSTURE,
    }
