"""Shared minimal toolbox inventory for tests that drive `CandidateProducer.produce`.

ROADMAP STEP 7 (2026-08-12). Before Step 7, `produce()` never consulted
`snapshot["toolbox"]`, so unit tests of DOWNSTREAM gates (RR floor, objective
resolution, mission lifecycle, trace fields) could pass `snapshot={}` and still
obtain a candidate. Step 7 made Terra's selected tool a real precondition:
a thesis may not be executed through an expression the market never produced.

Those fixtures were therefore encoding the pre-Step-7 contract. They are not
wrong about what they test; their snapshot simply has to satisfy the upstream
gate now, exactly as it already has to carry continuity and derived-state facts.

This helper is the single place that knowledge lives, so a future change to the
catalog shape updates every caller at once.
"""


#: STEP 4B.12 §7 UNIT 7 — "SOME EXECUTABLE TOOL EXISTS", and nothing more.
#:
#: Suites that test the RR floor, objective resolution, session evidence or
#: mechanical sovereignty all need the producer to get PAST the tool gate so it
#: can reach the proposition they actually care about. Every one of them used
#: `ifvg` for that, because it happened to be executable. Unit 7 quarantined
#: IFVG from execution authority, and 31 assertions across five suites failed --
#: none of them about IFVG.
#:
#: This constant is the one place that knowledge lives, so the next family to
#: change authority updates every caller at once.
#:
#: WHY PLAIN FVG. Not convenience -- it is the only currently executable family
#: with a PROVEN neutrality argument for these particular subjects. Unit 6
#: certified behaviourally (`test_production_fvg_stop_ownership`) that a plain
#: FVG cannot author the production stop or target: those belong to the
#: Terra-selected structural invalidation and the authorized objective. So an
#: FVG exemplar cannot contaminate an RR-floor test, which is precisely the
#: suite most at risk of a fixture quietly changing its own subject.
#:
#: It means ONLY "an executable expression exists". It is not the preferred,
#: best, default or fallback tool, and nothing may read it as ranking doctrine.
EXECUTABLE_TOOL_EXEMPLAR = "fvg"


def detected(*families, direction: str = "both", eligible: bool = True,
             source_tf: str = "5m") -> dict:
    """A snapshot fragment whose toolbox detected `families`, execution-eligible.

        detected("fvg")                    -> bullish_fvg AND bearish_fvg
        detected("fvg", direction="bearish") -> bearish only
        detected("ifvg", eligible=False)   -> provisional, refused by the gate

    DEFAULTS TO BOTH SIDES on purpose. These callers are asserting downstream
    behaviour and only need the selected expression to EXIST; pinning one side
    would make them fail on direction rather than on what they are testing.
    Direction compatibility itself is tested where it belongs, in
    tests/test_authorized_tool_catalog.py.
    """
    sides = ("bullish", "bearish") if direction == "both" else (direction,)
    #: STEP 4B.12 §6 UNIT 6 — PLAIN FVG IS PUBLISHED PER EXACT OCCURRENCE.
    #:
    #: `run_toolbox` now emits `tool_instances`, and `authorized_tool_catalog`
    #: builds plain-FVG entries from those exact occurrences rather than from
    #: the collapsed one-row-per-tool compatibility shape. A snapshot carrying
    #: only `tool_candidates` is treated as a pre-Unit-6 archive: readable, but
    #: with no provable occurrence identity it may not author execution.
    #:
    #: These fixtures assert DOWNSTREAM behaviour and only need the selected
    #: expression to exist and be eligible, so they are brought to production
    #: shape here -- exactly what this helper exists for. ONE eligible
    #: occurrence per (family, side) keeps Option-2 resolution unique; a fixture
    #: that wants the ambiguity refusal builds its own inventory.
    instances = [
        {"tool": f"{side}_{fam}", "family": fam, "direction": side,
         "source_tf": source_tf,
         "tool_id": f"{side}_{fam}@{source_tf}#step7",
         "occurrence_id": (f"FVG:CON.F.US.MNQ.U26:{source_tf}:"
                           f"2026-08-05T15:25:00+00:00"),
         "zone_low": 29860.0, "zone_high": 29866.0,
         "identity_evaluable": True,
         "temporal_class": "settled" if eligible else "provisional",
         "temporal_execution_eligible": eligible,
         "execution_eligible": eligible,
         "execution_ineligible_reason": (
             None if eligible
             else "TOOL_NOT_SETTLED: zone geometry depends on a forming bucket"),
         "score": 60}
        for fam in families if fam == "fvg" for side in sides
    ]
    return {"toolbox": {
        "preferred_tool": f"{sides[0]}_{families[0]}" if families else None,
        "tool_instances": instances,
        "tool_candidates": [
            {"tool": f"{side}_{fam}",
             "effective_status": "ready",
             "price_level": {
                 "level_type": f"{fam}_zone",
                 "direction": side,
                 "source_tf": source_tf,
                 "execution_eligible": eligible,
                 "temporal_class": "settled" if eligible else "provisional",
             }}
            for fam in families for side in sides
        ]}}


def with_tools(snapshot: dict, *families, **kw) -> dict:
    """`snapshot` plus a detected-tool inventory, without mutating the original."""
    return {**(snapshot or {}), **detected(*families, **kw)}


# ── EXEC-PRICE-FRESHNESS-1 (2026-08-20) ───────────────────────────────────────
#
# The producer prices exposure from a FRESH, SIDED, EXECUTABLE quote and fails
# closed without one. Before this, `market.current_price` -- the newest SETTLED
# candle close -- was the candidate's entry price, and on 2026-08-20 at 11:02:10
# that handed Luna 29404.25 while the contemporaneous minute traded
# 29423.25-29457.25, manufacturing a 66.00-point stop against a 29470.25
# protected high where the real distance was 29.50.
#
# Fixtures that predate this were encoding the old contract: a payload with no
# executable price. They are not wrong about what they test -- they simply have
# to carry the price the producer now requires, exactly as they already carry
# toolbox, continuity and derived-state facts.
#
# Zero-width by default so a fixture's single `price` is what gets used on BOTH
# sides; suites that care about sidedness pass a real bid and ask.
def execution_price(price=None, *, bid=None, ask=None, fresh=True, age=0.4,
                    available=True, reason=None) -> dict:
    """The executable block a live scan attaches to its snapshot."""
    if not available:
        return {"schema": "execution_price.v1", "available": False, "fresh": False,
                "source": None, "unavailable_reason": reason or "NO_QUOTE_PROVIDER",
                "best_bid": None, "best_ask": None, "last_trade": None,
                "captured_at": None, "age_seconds": None, "max_age_seconds": 5.0}
    bid = price if bid is None else bid
    ask = price if ask is None else ask
    return {"schema": "execution_price.v1", "available": True, "fresh": fresh,
            "source": "topstepx_realtime_quote",
            "unavailable_reason": None if fresh else "UNRELIABLE_STALE_QUOTE",
            "best_bid": bid, "best_ask": ask, "last_trade": bid,
            "captured_at": "2026-08-20T15:02:00+00:00", "age_seconds": age,
            "max_age_seconds": 5.0,
            "bullish_executable": ask, "bearish_executable": bid}


def priced(market: dict) -> dict:
    """`market` plus an executable price matching its settled `current_price`.

    For fixtures whose subject is a DOWNSTREAM gate and which only ever needed
    one number to stand for "where the market is".
    """
    m = dict(market or {})
    if "execution_price" not in m:
        m["execution_price"] = execution_price(m.get("current_price"))
    return m
