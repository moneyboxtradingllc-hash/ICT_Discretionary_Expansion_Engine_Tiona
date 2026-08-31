"""COGNITION-ESCALATION-ROUTER-1 -- which cognition tier THIS scan deserves.

SHADOW ONLY. Nothing here routes a real call, changes a payload, or touches
candidate/qualification/risk/execution. `route` is a pure function over evidence
the organism already holds; `observe` writes the verdict to a SEPARATE sink.

WHY THE TIER IS CHOSEN PRE-PROVIDER. The architecture law is one decision model
per decision. If a second model graded the first one's answer, Terra would be
Luna's supervisor and there would be two decision models in one decision. So the
tier is picked from MECHANICAL state, before any external call exists to route,
and no field produced by a model is ever read here -- not output, not
confidence, not `narrative_direction` (whose feedback into mechanical authority
is the quarantined `narrative_engine.py:91` loop).

THE RULE (ruled 2026-08-24; R2 retired from authority 2026-08-25 on measured
evidence -- see below):

    TERRA_SHADOW if  R1  path_contested
                  OR R4  (counter_path_at_location AND transfer_evidence_present)
                  OR R5  counter_path_objective_horizon_conflict
    otherwise LUNA_SHADOW

R3 IS ALSO RETIRED FROM AUTHORITY (2026-08-25), for a different reason than R2
and an equally measured one: across the corpus, `counter_path_at_location` fired
on 224 scans and `counter_path_at_location AND intervening_protected_structure`
fired on the same 224. The conjunction withheld ZERO cases, so R3 was
`counter_path_at_location` wearing a second term -- and escalating on counter
path alone is exactly what the doctrine forbids. The cause is the aggregation:
`intervening_protected_structure` asks whether ANY published objective sits
behind intact protected structure, across both sides, and at an 83.2% base rate
that is nearly always true once price stands at a zone at all.

What R3 was REACHING for is R5, `counter_path_objective_horizon_conflict`: a
genuine choice between a nearer, structurally defensible objective and a farther
authorised one that can only be reached THROUGH that same structure. Measured
before it was given authority -- it fires on 77 of 224 counter-path scans and
WITHHOLDS 65.6% of them (R3 withheld 0.0%), and it does not saturate with
catalog density (60.9% at eight-plus rows at location, dipping to 20.0% at
seven; retired R2 reached 100% and stayed).

R5 IS THE QUESTION TERRA IS BEING PAID FOR: how far is a valid counter-path
reaction justified in carrying its thesis before it must traverse structure that
still belongs to the active path?

R2 `bidirectional_at_location` IS MEASURED AND PUBLISHED, AND HAS NO AUTHORITY.
It was ruled as an escalation and then disqualified by its own shadow
measurement: across 975 archived scans its activation is monotonic in the number
of catalog rows standing at price -- 0% at one row, 11.7% at two, 43.6% at three,
84.4% at five, 100% at seven or more -- and the identical curve holds with the
design day excluded. It answers "did enough objects pile up at price for both
directions to appear", not "is the market presenting two genuinely competing
executable narratives". A representation defect, not an outcome-tuning decision:
on the design session it fired on 76.3% of scans while five other sessions
produced 0.0%, and the density curve explains both. A stronger representation
would demand independently executable opportunities on each side; that is new
mechanics and is NOT built here -- the router consumes existing truth, it does
not grow a second intelligence engine because one flag failed certification.

ESCALATION IS COGNITIVE SUPPORT, NOT PERMISSION. Nothing here gates a trade.
`terra_shadow` at 2026-08-24 10:52 does not mean the counter-path short was
wrong -- that reaction ran roughly 55 points in favour. It means the scan was a
LAYERED situation: a real bearish reaction taken INSIDE an established bullish
path with intact protected structure in front of the objective. A bullish active
path never forbids a short. The tier says which cognition the scan deserves, and
ownership stays EVIDENCE, never authorisation.

NO WEIGHTED SCORE. Reasons are named booleans, never summed. A score would let
three weak signals outvote the absence of a path, and would make the threshold
-- not the evidence -- the thing under discussion. It would also have HIDDEN the
R2 defect: a density-driven flag carrying partial weight degrades quietly,
whereas a named boolean either holds authority or does not.

WHY THE CONJUNCTIONS ARE NOT SEPARATE RULES. `intervening_protected_structure`
was measured at 71.1% prevalence (816/1147 objectives on the archived corpus).
Escalating on it alone would escalate almost everything, which is not a router
-- it is a rename of "always Terra". It earns its place only as a qualifier on
an already-counter-path location. The same holds for `transfer_evidence_present`
and for `counter_path_at_location` standing alone.
"""
from __future__ import annotations

TERRA_SHADOW = "terra_shadow"
LUNA_SHADOW = "luna_shadow"

#: The SAME adjacency vocabulary execution uses (`paper_execution.order_builder`
#: `_IN_ZONE_RELATIONS`). "At location" must mean the same thing to the router
#: that it means to the order builder, or the router would be reasoning about a
#: geometry no other component recognises.
AT_LOCATION_RELATIONS = frozenset({"inside_zone", "touching_zone"})

DIRECTIONS = ("bullish", "bearish")
OPPOSITE = {"bullish": "bearish", "bearish": "bullish"}

REASON_CONTESTED = "path_contested"                                        # R1
REASON_COUNTER_AND_INTERVENING = "counter_path_at_location+intervening_protected_structure"  # R3
REASON_COUNTER_AND_TRANSFER = "counter_path_at_location+transfer_evidence_present"           # R4

#: R2, RETIRED FROM AUTHORITY. The name is kept rather than renumbered so the
#: audit history stays legible: a report that says "R2 was measured and retired"
#: can still be matched to this code. It is never appended to `reasons`.
RETIRED_REASON_BIDIRECTIONAL = "bidirectional_at_location"

#: R3, RETIRED FROM AUTHORITY 2026-08-25 -- kept named for audit continuity,
#: never appended to `reasons`. See the module docstring for the measurement.
RETIRED_REASON_COUNTER_AND_INTERVENING = REASON_COUNTER_AND_INTERVENING

REASON_HORIZON_CONFLICT = "counter_path_objective_horizon_conflict"           # R5

AUTHORITATIVE_REASONS = (REASON_CONTESTED, REASON_COUNTER_AND_TRANSFER,
                         REASON_HORIZON_CONFLICT)


def _at_location(tool_catalog) -> list:
    """Rows where price actually STANDS, by the shared relation vocabulary."""
    return [r for r in (tool_catalog or [])
            if isinstance(r, dict)
            and str(r.get("price_relation") or "") in AT_LOCATION_RELATIONS]


def _directions_at_location(rows) -> set:
    return {str(r.get("direction") or "") for r in rows} & set(DIRECTIONS)


def transfer_evidence_present(active_path_state) -> bool:
    """TRUE only for evidence the producer AFFIRMS.

    `transfer_evidence` publishes truthful nulls: `opposing_market_structure_shift`
    and `opposing_displacement` are `None` because this producer cannot back a
    `false`. `any(dict.values())` would be correct today by accident and wrong
    the moment a null becomes a string -- and treating "unknown" as "present"
    would escalate on the absence of knowledge, which is the exact inversion
    `path_state_unavailable` exists to prevent.
    """
    te = ((active_path_state or {}).get("transfer_evidence") or {})
    return any(v is True for v in te.values())


def intervening_protected_structure(objective_catalog) -> bool:
    """Does ANY published objective sit behind an intact protected level?

    PER-OBJECTIVE FACT, PER-SCAN QUESTION. `protected_level_between_entry_and_target`
    is computed for each objective; the router asks one question per scan, so the
    aggregation must be stated rather than assumed. ANY is the truthful reading:
    the scan contains a defended path to something the Brain may legitimately
    choose. This is also precisely why it cannot escalate alone -- see the
    71.1% measurement in the module docstring.
    """
    return any(bool((o or {}).get("protected_level_between_entry_and_target"))
               for o in (objective_catalog or []) if isinstance(o, dict))


def same_level(a, b, tick_size=None) -> bool:
    """Do two prices denote ONE structural level?

    Raw float equality would make the predicate depend on producer rounding, so
    equality is tick-tolerant: within half a tick is the same tradeable price.

    HONEST BOUND. `enumerate_objectives` builds protected-swing objectives from
    `protected_swings.protected_high/low`, while the intervening rows come from
    `protected_swings.by_timeframe` -- two views of one tracker that share no
    `swing_id`. No persistent structural identifier exists to join them, and this
    unit does not invent one, so this is PRICE identity, not proven object
    identity. Recorded as a limitation rather than dressed up as more.
    """
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if tick_size and float(tick_size) > 0:
        return abs(a - b) <= float(tick_size) / 2.0
    return round(a, 4) == round(b, 4)


def _signed_distance(price, reference, direction):
    """Positive = further along the trade's OWN direction. Never absolute:
    absolute distance would let an objective behind the entry pose as a horizon."""
    return (reference - price) if direction == "bearish" else (price - reference)


def horizon_conflict(objective_catalog, direction, reference, tick_size=None):
    """R5 -- is there a genuine near/far horizon CHOICE on the trade's own side?

    Returns (fired, detail). Requires, in order:

      * two or more DISTINCT objectives `valid_for` this direction, each ahead of
        the reference by signed distance (ordering law, no cross-side mixing,
        never array order)
      * the NEAREST one has a clean approach -- if even it sits behind structure
        there is no defensible near destination, hence no choice
      * some farther one is blocked by intact protected structure
      * HORIZON-B: the level blocking that farther objective IS the near
        objective

    The last clause is what separates this from the retired R3. Measured against
    the weaker variant (drop it) on 975 scans, the two differ on five scans of a
    single 70-second episode, where the near destination was a liquidity pool
    rather than protected structure -- banking there is not "banking at the
    structure that owns the path", so the narrower reading is the faithful one.
    """
    if not direction or reference is None:
        return False, None
    try:
        ref = float(reference)
    except (TypeError, ValueError):
        return False, None

    ahead = []
    for o in (objective_catalog or []):
        if not isinstance(o, dict) or o.get("valid_for") != direction:
            continue
        if o.get("price") is None:
            continue
        try:
            d = _signed_distance(float(o["price"]), ref, direction)
        except (TypeError, ValueError):
            continue
        if d > 0:
            ahead.append((d, o))
    if len(ahead) < 2:
        return False, None
    ahead.sort(key=lambda t: t[0])

    # One structural level published twice must not pose as a near/far PAIR.
    unique = []
    for d, o in ahead:
        if not any(same_level(o["price"], u["price"], tick_size) for _, u in unique):
            unique.append((d, o))
    if len(unique) < 2:
        return False, None

    near = unique[0][1]
    if near.get("protected_level_between_entry_and_target"):
        return False, None
    blocked = [o for _, o in unique[1:]
               if o.get("protected_level_between_entry_and_target")]
    if not blocked:
        return False, None

    matched = [o for o in blocked
               if same_level(o.get("nearest_intervening_protected_level"),
                             near.get("price"), tick_size)]
    if not matched:
        return False, None
    return True, {
        "near_price": near.get("price"), "near_kind": near.get("kind"),
        "far_prices": [o.get("price") for o in matched],
        "blocking_level": matched[0].get("nearest_intervening_protected_level"),
    }


def route(*, active_path_state=None, tool_catalog=None, objective_catalog=None,
          reference_price=None, tick_size=None) -> dict:
    """Pick the shadow tier. Pure: no I/O, no clock, no provider, no mutation.

    Returns the verdict AND every predicate that produced it, so the record can
    be audited without re-deriving it from inputs that no longer exist.
    """
    aps = active_path_state or {}
    unavailable = aps.get("state_available") is False

    rows = _at_location(tool_catalog)
    dirs = _directions_at_location(rows)

    # DATA QUALITY IS NEVER AN ESCALATION. When path state is unavailable the
    # organism does not know less about the market than Terra could recover --
    # it holds no state at all, and a stronger model cannot manufacture missing
    # truth. Escalating here would buy the expensive tier precisely when there
    # is nothing extra for it to read.
    owner = aps.get("owner") if not unavailable else None
    owner = owner if owner in DIRECTIONS else None

    # ESTABLISHED OWNERSHIP ONLY. `forming_direction` is an unconfirmed causal
    # hypothesis; routing on it would make a rejected raid -- ordinary inside a
    # retracement -- buy the expensive tier. This is what keeps "forming_direction
    # alone does not escalate" structurally true rather than merely tested.
    counter_at_location = bool(owner) and OPPOSITE[owner] in dirs
    bidirectional = len(dirs) > 1
    contested = (not unavailable) and str(aps.get("status") or "") == "contested"
    transfer = (not unavailable) and transfer_evidence_present(aps)
    intervening = intervening_protected_structure(objective_catalog)

    horizon, horizon_detail = horizon_conflict(
        objective_catalog, OPPOSITE[owner] if owner else None,
        reference_price, tick_size)

    reasons = []
    if contested:
        reasons.append(REASON_CONTESTED)
    # R2 and R3 are deliberately absent: measured, published below, no authority.
    if counter_at_location and transfer:
        reasons.append(REASON_COUNTER_AND_TRANSFER)
    if counter_at_location and horizon:
        reasons.append(REASON_HORIZON_CONFLICT)

    return {
        "tier": TERRA_SHADOW if reasons else LUNA_SHADOW,
        "reasons": reasons,
        "predicates": {
            "path_contested": contested,
            "bidirectional_at_location": bidirectional,
            "counter_path_at_location": counter_at_location,
            "transfer_evidence_present": transfer,
            "intervening_protected_structure": intervening,
            "path_state_unavailable": unavailable,
            "counter_path_objective_horizon_conflict": bool(counter_at_location
                                                            and horizon),
        },
        "horizon_detail": horizon_detail if counter_at_location else None,
        # MEASURED, NOT AUTHORITATIVE. Published so the retired flag keeps
        # accruing evidence for a future BIDIRECTIONAL-EXECUTABLE-CONFLICT unit
        # without being able to route a single scan in the meantime.
        "telemetry_only": {
            RETIRED_REASON_BIDIRECTIONAL: bidirectional,
            RETIRED_REASON_COUNTER_AND_INTERVENING: counter_at_location and intervening,
        },
        "path_owner": owner,
        "path_status": aps.get("status") if not unavailable else None,
        "at_location_count": len(rows),
        "directions_at_location": sorted(dirs),
    }


# ══════════════════════════════════════════════════════════════════════════════
# THE SINK. Deliberately NOT the Brain payload.
#
# Writing the verdict into the snapshot or `brain_input` would make the router
# visible to the model, and "shadow" would then be a claim resting on the model
# ignoring a field it can see. A separate file makes zero-behaviour-difference
# STRUCTURAL: there is no path from this record back into the scan.
# ══════════════════════════════════════════════════════════════════════════════
import json                                                        # noqa: E402
import os                                                          # noqa: E402

SINK_DIR_ENV = "COGNITION_SHADOW_DIR"
DEFAULT_SINK_DIR = os.path.join("data", "ai_shadow")
SINK_BASENAME = "cognition_escalation_shadow"


def sink_path(when=None) -> str:
    base = os.environ.get(SINK_DIR_ENV) or DEFAULT_SINK_DIR
    day = (when or "")[:10].replace("-", "") or "undated"
    return os.path.join(base, f"{SINK_BASENAME}_{day}.jsonl")


def observe(*, snapshot=None, brain_input=None, symbol=None,
            tick_size=None) -> dict:
    """Route this scan and APPEND the verdict. Never raises, never mutates.

    The caller is a live production scan. An exception here must not cost a
    trading decision, and neither must a full disk -- so every failure path
    returns the verdict (or None) and writes nothing. Nothing about the scan
    depends on the return value.
    """
    try:
        snap = snapshot or {}
        bi = brain_input or {}
        # The reference comes from the SAME authority the objective catalog was
        # built against (`brain_input["market"]["current_price"]`). Re-deriving
        # it here would be a second pricing model, and EXEC-PRICE-FRESHNESS
        # exists because a settled close once masqueraded as an executable one.
        verdict = route(
            active_path_state=snap.get("active_path_state"),
            tool_catalog=bi.get("authorized_tool_catalog"),
            objective_catalog=bi.get("authorized_objectives"),
            reference_price=(bi.get("market") or {}).get("current_price"),
            tick_size=tick_size)
        when = str(snap.get("timestamp") or "")
        record = dict(verdict)
        record["timestamp"] = when
        record["symbol"] = symbol
        record["contract_id"] = snap.get("contract_id")
        try:
            path = sink_path(when)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError:
            pass
        return verdict
    except Exception:  # noqa: BLE001 -- shadow telemetry may never cost a scan
        return None
