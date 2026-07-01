"""
Adaptive Learning — Phase 5: Live Mutation Authority (LIVE, DEFENSIVE_ONLY).

Promotes the ADAPTIVE-4 shadow mutation into a LIVE defensive overlay. It reads
the policy + mutation already on the snapshot and exposes defensive-adjusted
candidate fields that downstream layers MAY consume to become STRICTER — never
more aggressive.

CONSTITUTION — DEFENSIVE_ONLY, and it exposes OVERLAYS; it does NOT overwrite
authoritative fields:
  * it writes NEW snapshot keys (adaptive_live_authority / adaptive_confidence /
    adaptive_block / adaptive_size)
  * it NEVER overwrites ai_context, qualification, playbook, tool, direction, the
    Brain confidence, or the risk governor.
  * confidence overlay is exposed ONLY when final < original (never upward).
  * size overlay is exposed ONLY when a real qty exists and final < original
    (size is never invented).
  * the soft block can only ADD a no-trade reason; it can never approve a trade
    or override any safety/ops/risk/broker mechanism.

Never raises.
"""
from __future__ import annotations

AUTHORITY_LEVEL = "live_defensive"
POSTURE         = "DEFENSIVE_ONLY"
SOURCE          = "adaptive_live_authority"


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def apply_adaptive_live_authority(snapshot: dict) -> dict:
    """Read snapshot['adaptive_policy'] + ['adaptive_mutation'], write the live
    defensive overlays onto the snapshot, and return the adaptive_live_authority
    record. Never raises; never overwrites forbidden categories."""
    try:
        snap = snapshot if isinstance(snapshot, dict) else {}
        mutation = snap.get("adaptive_mutation")
        mutation = mutation if isinstance(mutation, dict) else {}

        orig_conf = mutation.get("original_confidence")
        new_conf  = mutation.get("new_confidence")
        orig_qty  = mutation.get("original_qty")
        new_qty   = mutation.get("new_qty")
        trade_blocked = bool(mutation.get("trade_blocked"))
        reasons = list(mutation.get("mutation_reasoning") or [])
        applied_rules = list(mutation.get("mutation_types") or [])

        # ── Confidence: DOWNWARD ONLY. Exposed only when strictly reduced. ──
        confidence_adjusted = (
            _is_num(orig_conf) and _is_num(new_conf) and new_conf < orig_conf
        )
        final_conf = new_conf if confidence_adjusted else orig_conf

        # ── Size: real qty only, DOWNWARD ONLY. Never invented. ──
        size_adjusted = (
            _is_num(orig_qty) and _is_num(new_qty) and new_qty < orig_qty
        )
        final_qty = new_qty if size_adjusted else orig_qty

        trade_soft_blocked = trade_blocked
        applied = bool(confidence_adjusted or size_adjusted or trade_soft_blocked)

        # forbidden-action verification: post-condition on the EXPOSED final
        # values — they may only ever be <= the originals (never upward). Computed
        # from final (not raw mutation) so a malformed upward mutation is simply
        # not exposed, and this stays True.
        forbidden_ok = (
            (not _is_num(orig_conf) or not _is_num(final_conf) or final_conf <= orig_conf)
            and (not _is_num(orig_qty) or not _is_num(final_qty) or final_qty <= orig_qty)
        )

        live = {
            "authority_level":            AUTHORITY_LEVEL,
            "posture":                    POSTURE,
            "applied":                    applied,
            "confidence_adjusted":        confidence_adjusted,
            "size_adjusted":              size_adjusted,
            "trade_soft_blocked":         trade_soft_blocked,
            "original_confidence":        orig_conf,
            "final_confidence":           final_conf,
            "confidence_source":          SOURCE,
            "original_qty":               orig_qty,
            "final_qty":                  final_qty,
            "block_reason":               (reasons if trade_soft_blocked else None),
            "applied_rules":              applied_rules,
            "forbidden_actions_verified": bool(forbidden_ok),
        }
        snap["adaptive_live_authority"] = live

        # ── Confidence overlay (defensive; never overwrites raw confidence) ──
        if confidence_adjusted:
            snap["adaptive_confidence"] = {
                "original": orig_conf,
                "final":    final_conf,
                "source":   SOURCE,
                "reason":   reasons,
            }

        # ── Soft-block overlay (stable field; blocked flag always present) ──
        snap["adaptive_block"] = {
            "blocked": trade_soft_blocked,
            "source":  SOURCE,
            "reason":  (reasons if trade_soft_blocked else []),
        }

        # ── Size overlay (only when a real qty was reduced) ──
        if size_adjusted:
            snap["adaptive_size"] = {
                "original": orig_qty,
                "final":    final_qty,
                "source":   SOURCE,
            }

        return live
    except Exception as exc:  # noqa: BLE001
        return _neutral(reason=f"live_authority_error:{type(exc).__name__}")


def adaptive_entry_block_reason(snapshot: dict) -> "str | None":
    """Central consumer helper for entry gates. Returns a DEFENSIVE no-trade
    reason string when the adaptive soft block is active, else None. It can ONLY
    block — it never approves, never overrides safety/ops/risk. Never raises."""
    try:
        ab = (snapshot or {}).get("adaptive_block") or {}
        if ab.get("blocked"):
            reasons = ab.get("reason") or ["defensive block"]
            return "adaptive: soft veto — " + "; ".join(str(r) for r in reasons)
        return None
    except Exception:  # noqa: BLE001
        return None


def resolve_final_confidence(original_confidence, snapshot: dict):
    """DEFENSIVE confidence resolver for a legal consumer. Returns the adaptive
    final confidence when it is LOWER than the caller's original, else the
    original. Capped with min() so it can only ever LOWER — never raise, never
    invent (returns original untouched when no overlay). Never raises."""
    try:
        if not _is_num(original_confidence):
            return original_confidence
        ac = (snapshot or {}).get("adaptive_confidence") or {}
        f, o = ac.get("final"), ac.get("original")
        if _is_num(f) and _is_num(o) and f < o:
            return min(original_confidence, f)
        return original_confidence
    except Exception:  # noqa: BLE001
        return original_confidence


def resolve_final_qty(original_qty, snapshot: dict):
    """DEFENSIVE size resolver for a legal sizing consumer (ADAPTIVE-7).

    Returns a qty that may ONLY be lower than the caller's original (the caller's
    risk/buying-power-capped size). Resolution order:
      1. a pre-computed ``adaptive_size`` overlay (final < original), or
      2. else — at the live sizing site where a real qty finally exists — derive
         the reduction from ``adaptive_policy.risk_reduction_recommended`` via the
         single halving rule in the mutation engine (floor, min 1).
    Always ``min()``-capped to the caller's original: never raises, never invents,
    never exceeds the risk max. Never raises."""
    try:
        if not _is_num(original_qty) or original_qty <= 0:
            return original_qty

        # 1) explicit pre-computed overlay wins
        asz = (snapshot or {}).get("adaptive_size") or {}
        f, o = asz.get("final"), asz.get("original")
        if _is_num(f) and _is_num(o) and f < o:
            return min(original_qty, f)

        # 2) live derivation from policy over the real qty (single source of the
        #    halving rule = the mutation engine; keeps DEFENSIVE_ONLY downward-only)
        policy = (snapshot or {}).get("adaptive_policy") or {}
        if policy.get("risk_reduction_recommended"):
            from adaptive_learning.adaptive_mutation_engine import mutate_candidate
            nq = mutate_candidate({"qty": original_qty}, policy).get("new_qty")
            if _is_num(nq) and nq < original_qty:
                return min(original_qty, nq)

        return original_qty
    except Exception:  # noqa: BLE001
        return original_qty


def record_live_size_consumption(snapshot: dict, original_qty, final_qty,
                                 reason=None) -> dict:
    """Persist the ADAPTIVE-7 size-consumption forensics onto
    ``snapshot['adaptive_live_consumption']`` (created if absent, updated if the
    ADAPTIVE-6 consumption pass already ran). Records only a genuine reduction.
    Never raises; returns the consumption record."""
    try:
        snap = snapshot if isinstance(snapshot, dict) else {}
        rec = snap.get("adaptive_live_consumption")
        if not isinstance(rec, dict):
            rec = {
                "adaptive_confidence_consumed": False,
                "adaptive_size_consumed":       False,
                "original_live_confidence":     None,
                "final_live_confidence":        None,
                "original_live_qty":            None,
                "final_live_qty":               None,
                "source":                       SOURCE,
                "posture":                      POSTURE,
                "notes":                        [],
            }
        reduced = _is_num(original_qty) and _is_num(final_qty) and final_qty < original_qty
        rec["adaptive_size_consumed"] = bool(reduced)
        rec["original_live_qty"]      = original_qty
        rec["final_live_qty"]         = final_qty
        rec["adaptive_final_qty"]     = final_qty
        rec["adaptive_size_source"]   = SOURCE
        rec["adaptive_size_reason"]   = (
            reason or (f"qty {original_qty} -> {final_qty} (adaptive defensive)"
                       if reduced else "no size reduction"))
        if reduced:
            rec.setdefault("notes", []).append(rec["adaptive_size_reason"])
        snap["adaptive_live_consumption"] = rec
        return rec
    except Exception:  # noqa: BLE001
        return snapshot.get("adaptive_live_consumption", {}) if isinstance(snapshot, dict) else {}


def consume_adaptive_overlays(snapshot: dict) -> dict:
    """LIVE, DEFENSIVE_ONLY consumption of the exposed overlays.

    Confidence: lowers ``confidence_fusion.combined_confidence`` to the adaptive
    final when that is lower (never raises). Size: recorded when a live qty
    overlay is present (the mainline qty owner is order_builder, a guarded layer,
    so size is resolved via ``resolve_final_qty`` at the legal sizing site, not
    forced here). Soft-block supremacy and every safety layer are untouched — this
    only lowers a derived value. Writes forensics to
    ``snapshot['adaptive_live_consumption']`` and returns that record. Never raises.
    """
    try:
        snap = snapshot if isinstance(snapshot, dict) else {}
        fusion = snap.get("confidence_fusion")
        notes = []

        # ── Confidence consumption (defensive, downward-only) ──
        consumed_conf = False
        orig_conf = final_conf = None
        if isinstance(fusion, dict):
            orig_conf = fusion.get("combined_confidence")
            final_conf = resolve_final_confidence(orig_conf, snap)
            if _is_num(orig_conf) and _is_num(final_conf) and final_conf < orig_conf:
                fusion["combined_confidence"] = final_conf
                consumed_conf = True
                notes.append(
                    f"combined_confidence {orig_conf} -> {final_conf} (adaptive defensive)")

        # ── Size consumption (recorded; enforced at the legal sizing site) ──
        asz = snap.get("adaptive_size") or {}
        consumed_size = False
        orig_qty = asz.get("original") if isinstance(asz, dict) else None
        final_qty = orig_qty
        if _is_num(asz.get("final")) and _is_num(orig_qty) and asz["final"] < orig_qty:
            final_qty = asz["final"]
            consumed_size = True
            notes.append(f"qty {orig_qty} -> {final_qty} (adaptive defensive)")

        record = {
            "adaptive_confidence_consumed": consumed_conf,
            "adaptive_size_consumed":       consumed_size,
            "original_live_confidence":     orig_conf,
            "final_live_confidence":        final_conf,
            "original_live_qty":            orig_qty,
            "final_live_qty":               final_qty,
            "source":                       SOURCE,
            "posture":                      POSTURE,
            "notes":                        notes,
        }
        snap["adaptive_live_consumption"] = record
        return record
    except Exception as exc:  # noqa: BLE001
        rec = {
            "adaptive_confidence_consumed": False,
            "adaptive_size_consumed":       False,
            "original_live_confidence":     None,
            "final_live_confidence":        None,
            "original_live_qty":            None,
            "final_live_qty":               None,
            "source":                       SOURCE,
            "posture":                      POSTURE,
            "notes":                        [f"consume_error:{type(exc).__name__}"],
        }
        if isinstance(snapshot, dict):
            snapshot["adaptive_live_consumption"] = rec
        return rec


def _neutral(reason: str = "no adaptive live authority") -> dict:
    return {
        "authority_level":            AUTHORITY_LEVEL,
        "posture":                    POSTURE,
        "applied":                    False,
        "confidence_adjusted":        False,
        "size_adjusted":              False,
        "trade_soft_blocked":         False,
        "original_confidence":        None,
        "final_confidence":           None,
        "confidence_source":          SOURCE,
        "original_qty":               None,
        "final_qty":                  None,
        "block_reason":               None,
        "applied_rules":              [],
        "forbidden_actions_verified": True,
        "explanation":                reason,
    }
