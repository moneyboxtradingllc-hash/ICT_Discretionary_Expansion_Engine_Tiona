"""ACTIVE-PATH-STATE-1 — durable market-path ownership.

    DETECTORS -> immutable occurrences -> deterministic synthesis
              -> compact active_path_state -> discretionary judgement

THE DEFECT THIS CLOSES. On 2026-08-24 at 10:52 the Brain was asked which side
owned the market. Three models on identical payloads -- gpt-5.6-luna, -terra and
-sol, 19 calls -- answered BEARISH, 0/19 identifying the bullish leg that had
produced 29 structural breaks against 3 in the preceding forty minutes and three
successively higher defended lows. That was not a reasoning failure. It was the
only inference the payload supported: every model read ownership off the bearish
FVG sitting at price, because nothing else in the snapshot could answer.

The chronology was never missing. It was never written down:

    structure[tf].bos / mss   a PRESENT-TENSE boolean; gone one scan later
    protected swing ladder    the tracker POPS the old level on replacement, so
                              28953.50 -> 28962.75 -> 28979.50 -> 29081.50 was
                              destroyed as it formed

The durable occurrence ledger already existed for exactly this class of problem
("the organism could say 'I see a sweep' and, one candle later, 'what sweep?'")
and already ran in production carrying LIQUIDITY_SWEEP alone. This module MINTS
the remaining event classes and derives current state from them; the scan cycle
remains the sole writer to that store, so the ledger-consumer invariant from
LIQUIDITY-SWEEP-EPISODE-IDENTITY-1 is preserved -- nothing here imports it.

TWO KINDS OF TRUTH, DELIBERATELY SEPARATED:
    FACTS    immutable, durable, append-only, never re-derived
    STATE    recomputed every scan, never persisted, never trusted from disk

OWNERSHIP IS EVIDENCE, NOT AUTHORISATION. `owner` may never forbid a trade. A
lawful counter-path reaction -- bearish entry inside a bullish path -- must stay
executable; distinguishing that from a path REVERSAL is the entire purpose.

FORBIDDEN BY CONSTRUCTION:
    * no majority voting (bullish_breaks > bearish_breaks -> bullish)
    * no scoring, confidence, thresholds on event counts
    * no trade direction, permission, prohibition, or prediction
    * no reading of the tool catalog, executable price, or any directional
      object at the current location -- proven by mutation over 594 archived
      scans: stripping every tool, and inverting every tool's direction, both
      leave owner/status/load-bearing chronology bit-identical.
"""
from __future__ import annotations

from market_data.causal_identity import (  # noqa: F401 - re-exported
    CAUSAL_IDENTITY_V1, CAUSAL_IDENTITY_V2,
    DEFAULT_CAUSAL_IDENTITY_VERSION, causal_event_key, identity_of,
    refusal_reason, resolve_version)

# ── EVENT VOCABULARY ─────────────────────────────────────────────────────────
LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"                   # already live in the ledger
STRUCTURE_BREAK = "STRUCTURE_BREAK"
PROTECTED_SWING_REGISTERED = "PROTECTED_SWING_REGISTERED"
PROTECTED_SWING_REPLACED = "PROTECTED_SWING_REPLACED"
PROTECTED_SWING_VIOLATED = "PROTECTED_SWING_VIOLATED"

#: A raid REJECTED on one side implies delivery toward the other. This mirrors
#: the doctrine `brain_prompt` already carries for BOTH directions and is the
#: only place a side is inferred from a sweep.
RAID_IMPLIES = {"below_low": "bullish", "above_high": "bearish"}
OPPOSITE = {"bullish": "bearish", "bearish": "bullish"}
#: Ordering only. Never summed, never scored.
TF_RESOLUTION = {"1m": 1, "3m": 2, "5m": 3, "15m": 4}
_TFS = ("15m", "5m", "3m", "1m")

#: `structure[tf].mss` is a bare boolean and the producer refuses to give it a
#: side (`_DIRECTION_BLIND_FAMILIES`). It is therefore NOT recorded as a
#: directional event and never participates in ownership or transfer. Inventing
#: its direction downstream would rebuild the authority inversion this
#: repository has removed twice.
MSS_HAS_NO_DIRECTION = "mss carries no direction in this producer"

STATE_UNAVAILABLE = "path_state_unavailable"

#: Why derived ownership was released. Diagnostic only -- no business logic may
#: branch on these strings.
RESET_NEW_SESSION = "new_production_session"
RESET_CONTRACT_ROLLOVER = "contract_rollover"
RESET_HISTORY_REVISION = "canonical_history_revision"


def production_session_key(timestamp) -> "str | None":
    """The production session a moment belongs to, in canonical exchange time.

    WHAT THIS ACTUALLY USES, precisely: the exchange TIMEZONE from
    `topstepx_session_authorization.PRODUCTION_WINDOW_TZ`, and then the
    exchange-local calendar date. It does NOT read `PRODUCTION_WINDOW_START`.
    An earlier docstring claimed it did; the claim was wider than the code and
    is corrected here rather than papered over.

    THE EQUIVALENCE THAT MAKES THAT SUFFICIENT, and its exact boundary. The
    production loop's own control flow bounds every timestamp this can observe
    to ONE exchange-local calendar day:

        production_window_open()      start <= HH:MM <  end     (same local day)
        before_production_window()             HH:MM <  start   (same local day)
        should_continue()             continues only if one of those holds

    Their union is [00:00, end) on a single local date, so the local date IS the
    production-session identity for every observable instant: a 02:00 pre-bell
    scan belongs to that day's upcoming session, and the loop does not scan
    after the close. A naive UTC date slice would NOT be equivalent -- it puts
    the 20:00Z-23:59Z part of a session on the following day -- which is why the
    canonical timezone is imported rather than assumed.

    THIS EQUIVALENCE IS LOAD-BEARING AND TESTED. If the production envelope ever
    widens past local midnight, the local date stops being the session identity
    and this must read `PRODUCTION_WINDOW_START` to decide which session a
    small-hours instant belongs to. A test pins the envelope so that change
    cannot pass silently.

    Returns None when the instant cannot be read -- absence, never a guess.
    """
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from broker.topstepx_session_authorization import PRODUCTION_WINDOW_TZ
        ts = str(timestamp or "").strip()
        if not ts:
            return None
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            from datetime import timezone as _tz
            dt = dt.replace(tzinfo=_tz.utc)
        return dt.astimezone(ZoneInfo(PRODUCTION_WINDOW_TZ)).strftime("%Y%m%d")
    except Exception:  # noqa: BLE001
        return None


def occurrence_id(contract, event_type, source_tf, event_time, discriminator=""):
    """Deterministic factual identity. The SAME tape event observed on ten
    consecutive scans mints ONE id, so re-observation is idempotent and a
    restart cannot duplicate history. Scan time is deliberately absent: it
    would make identity an artefact of when we looked."""
    tail = f":{discriminator}" if discriminator not in (None, "") else ""
    return f"{event_type}:{contract}:{source_tf}:{event_time}{tail}"


def extract_occurrences(snapshot: dict, prior_protected: dict, contract: str) -> list:
    """Immutable tape facts this snapshot witnessed.

    `prior_protected` is the PREVIOUS scan's `protected_swings.by_timeframe`,
    which is how a registration/replacement/violation becomes visible as the
    EVENT it is -- the tracker itself only ever exposes the current level.
    Never raises: evidence must not break the scan.

    CAUSAL-OCCURRENCE-IDENTITY-1 adds PROVENANCE, not new events. Every
    occurrence now carries enough about its own cause for `causal_event_key` to
    answer "which market event is this?" without consulting the scan clock:

        Category A   `source_bar_time` / `settled_edge_time`, read from the
                     snapshot's `settled_source` block -- the same settled
                     series `analyze_structure` and `analyze_liquidity` were
                     handed, so it names the bucket that actually authored the
                     claim.
        Category B   the tracker's own formation stamps. A VIOLATED event now
                     carries the DYING swing's `swing_id` and `registered_at`,
                     and a REPLACED event carries both ends of the transition.

    THE VIOLATED EMITTER WAS DROPPING WHAT IT ALREADY HELD. `old` is the prior
    tracker record and has carried `swing_id` all along; the emitter simply
    never read it, so every violation was published with `swing_id=None`. That
    is a plumbing defect in this function, not a question about protected-swing
    doctrine, and it is fixed here rather than by widening what the tracker
    publishes.

    ADDITIVE. `occurrence_id` and every existing field are unchanged, so a v1
    consumer -- which is still every production consumer -- reads exactly what
    it read before.
    """
    out = []
    try:
        liq = (snapshot or {}).get("liquidity") or {}
        st = (snapshot or {}).get("structure") or {}
        settled_source = (snapshot or {}).get("settled_source") or {}
        ts = str((snapshot or {}).get("timestamp") or "")

        def provenance(tf):
            """WHICH BAR authored this timeframe's confirmed claims, plus the
            scan that noticed. Absent rather than guessed: a snapshot built by
            an older path publishes no `settled_source`, and inventing a bar
            time from `ts` would recreate the very defect being removed."""
            block = settled_source.get(tf) or {}
            return {"source_bar_time": block.get("source_bar_time"),
                    "settled_edge_time": block.get("settled_edge_time"),
                    "observed_at": ts}

        for tf in _TFS:
            b = liq.get(tf) or {}
            if b.get("sweep_detected") and b.get("reclaim_detected"):
                d = b.get("sweep_direction")
                if d in RAID_IMPLIES:
                    # SECOND INSTANCE OF THE SAME PLUMBING DEFECT the VIOLATED
                    # emitter had. `analyze_liquidity` publishes the raided
                    # price inside `sweep_fact`, never at the top of the block,
                    # so `b.get("swept_level")` has been None on every sweep
                    # this function has ever emitted -- while the value sat one
                    # key away. Read-through only: no new field is computed and
                    # no detector is asked a new question.
                    fact = b.get("sweep_fact") or {}
                    lvl = b.get("swept_level")
                    if lvl is None:
                        lvl = fact.get("swept_level")
                    out.append({
                        "occurrence_id": occurrence_id(contract, LIQUIDITY_SWEEP, tf, ts, d),
                        "event_type": LIQUIDITY_SWEEP, "contract": contract,
                        "source_tf": tf, "event_time": ts, "sweep_direction": d,
                        "liquidity_side_taken": ("buy_side" if d == "above_high"
                                                 else "sell_side"),
                        "swept_level": lvl, "reclaimed": True,
                        "reclaim_basis": "same_bar_close_back_through_level",
                        **provenance(tf)})
            s = st.get(tf) or {}
            if s.get("bos") and s.get("bos_direction") in ("bullish", "bearish"):
                lvl = s.get("broken_level")
                out.append({
                    "occurrence_id": occurrence_id(
                        contract, STRUCTURE_BREAK, tf, ts,
                        f"{s['bos_direction']}@{lvl}"),
                    "event_type": STRUCTURE_BREAK, "contract": contract,
                    "source_tf": tf, "event_time": ts,
                    "direction": s.get("bos_direction"), "broken_level": lvl,
                    **provenance(tf)})

        now = (((snapshot or {}).get("protected_swings") or {})
               .get("by_timeframe") or {})
        for side_key, side in (("lows", "low"), ("highs", "high")):
            cur = (now.get(side_key) or {})
            prev = ((prior_protected or {}).get(side_key) or {})
            for tf, rec in cur.items():
                old = prev.get(tf)
                lvl = rec.get("level")
                if old is None:
                    out.append({
                        "occurrence_id": occurrence_id(
                            contract, PROTECTED_SWING_REGISTERED, tf,
                            rec.get("registered_at") or ts, f"{side}@{lvl}"),
                        "event_type": PROTECTED_SWING_REGISTERED,
                        "contract": contract, "source_tf": tf, "event_time": ts,
                        "side": side, "level": lvl, "basis": rec.get("basis"),
                        "swing_id": rec.get("swing_id"),
                        "registered_at": rec.get("registered_at"),
                        "observed_at": ts})
                elif old.get("level") != lvl:
                    out.append({
                        "occurrence_id": occurrence_id(
                            contract, PROTECTED_SWING_REPLACED, tf, ts,
                            f"{side}:{old.get('level')}->{lvl}"),
                        "event_type": PROTECTED_SWING_REPLACED,
                        "contract": contract, "source_tf": tf, "event_time": ts,
                        "side": side, "old_level": old.get("level"),
                        "level": lvl, "basis": rec.get("basis"),
                        "swing_id": rec.get("swing_id"),
                        # BOTH ENDS OF THE TRANSITION. A replacement is a
                        # relationship; naming only its destination cannot
                        # distinguish A->B from a later A->B after B->A.
                        "registered_at": rec.get("registered_at"),
                        "old_swing_id": old.get("swing_id"),
                        "old_registered_at": old.get("registered_at"),
                        "observed_at": ts})
            for tf, old in prev.items():
                if tf not in cur:
                    out.append({
                        "occurrence_id": occurrence_id(
                            contract, PROTECTED_SWING_VIOLATED, tf, ts,
                            f"{side}@{old.get('level')}"),
                        "event_type": PROTECTED_SWING_VIOLATED,
                        "contract": contract, "source_tf": tf, "event_time": ts,
                        "side": side, "level": old.get("level"),
                        # THE SWING THAT DIED, from the record that held it.
                        # Emitting None here made every violation causally
                        # anonymous and unable to be matched to its own birth.
                        "swing_id": old.get("swing_id"),
                        "registered_at": old.get("registered_at"),
                        "observed_at": ts})
    except Exception:  # noqa: BLE001 - evidence must never break the scan
        return out
    return out


class ActivePath:
    """Derived, recomputed, never persisted. Facts are durable; state is current."""

    def __init__(self, *, causal_identity_version=None):
        # EXPLICIT, NEVER INFERRED. The presence of v2 machinery in this build is
        # not permission to use it: an omitted version resolves to v1, which is
        # what every production caller passes today by simply not passing
        # anything. Who may select v2 in production is owned by the next unit.
        self.causal_identity_version = resolve_version(causal_identity_version)
        self.reset()

    def reset(self, reason: str = None):
        # Boundary identity is deliberately NOT cleared here: it is what the
        # NEXT comparison is made against, and clearing it would make every
        # reset look like a first observation.
        self._session_key = getattr(self, "_session_key", None)
        self._contract = getattr(self, "_contract", None)
        self.events: list = []
        self._seen: set = set()
        self.owner = "none"            # ESTABLISHED ownership ONLY
        self.forming_direction = None  # an unconfirmed causal hypothesis
        self.status = "none"
        self.origin = None
        self.load_bearing = None
        self.progression_tfs: set = set()
        self.ladder: list = []
        self.adverse_replacements: list = []
        self.releases: list = []
        self.last_invalidated = None
        #: v2 only. Events whose CAUSAL identity could not be established, and
        #: which were therefore refused rather than ingested under a guess.
        #: Counted so that "we saw nothing" and "we could not identify what we
        #: saw" stay distinguishable to a reader.
        self.unidentified: list = []
        self._prev_owner = "none"
        self._reset_reason = reason
        self.last_reset_reason = reason

    # ── helpers ─────────────────────────────────────────────────────────────
    def _leg_direction(self):
        """Direction of the leg being carried -- established OR merely forming.
        Ownership is a claim about the market; carrying a hypothesis is not."""
        return (self.owner if self.owner in ("bullish", "bearish")
                else self.forming_direction)

    def _supporting_side(self):
        return "low" if self._leg_direction() == "bullish" else "high"

    def enforce_lifecycle(self, timestamp, contract) -> "str | None":
        """Release derived ownership at a session or contract boundary.

        THE GUARANTEE MUST BE STRUCTURAL, NOT OPERATIONAL. Before this, an
        established path survived into the next production session for exactly
        one reason: the launcher happens to restart the process every morning.
        `ProductionScanCycle` is constructed once per launched loop, so nothing
        in the architecture prevented a leg established on Monday from still
        owning Tuesday's tape if the process stayed alive -- a safety property
        resting on an operating habit.

        A contract change is the harder version of the same error: an exact
        contract is a different instrument, and inheriting a bullish owner, a
        load-bearing level or a ladder across a rollover would file one
        instrument's structure under another's identity.

        FACTS ARE NOT TOUCHED. The occurrence ledger keeps every event forever
        and stays contract-scoped; only the derived CONCLUSION is released, and
        the next leg must be established causally from current-session evidence.

        Returns the reset reason, or None when nothing changed.
        """
        reason = None
        key = production_session_key(timestamp)
        contract = str(contract or "") or None
        if self._contract is not None and contract is not None \
                and contract != self._contract:
            reason = RESET_CONTRACT_ROLLOVER
        elif self._session_key is not None and key is not None \
                and key != self._session_key:
            reason = RESET_NEW_SESSION
        if reason:
            self.reset(reason)
        if key is not None:
            self._session_key = key
        if contract is not None:
            self._contract = contract
        return reason

    def ingest(self, occurrences: list):
        """Apply events in order. IDEMPOTENT BY OCCURRENCE IDENTITY.

        One factual event is one occurrence -- in memory exactly as on disk. A
        sweep is re-detected on every scan while its two-candle predicate holds,
        so an un-deduplicated ingest applied the same tape fact five or six
        times: the ladder could gain a level twice, and `transfer_evidence`
        counted stale copies of a counter-raid as though it had happened again.

        It also made a restart produce a DIFFERENT state from a continuous
        process, because ledger replay is deduplicated and live ingest was not.
        The two must converge, so the in-memory store adopts the ledger's rule.

        WHICH IDENTITY ANSWERS IS THE VERSION'S DECISION, and only the version's.

            v1   `occurrence_id` -- observation identity. What production runs.
            v2   `causal_event_key` -- market-event identity.

        There is no "try v2, fall back to v1". A fallback would dedup some
        events by what happened and others by when we looked, inside one
        session, with nothing in the state saying which answered where.

        UNDER v2, AN UNIDENTIFIABLE EVENT IS REFUSED, not ingested unguarded.
        Ingesting it undeduped would reintroduce exactly the multiple-counting
        this version exists to remove; ingesting it under a manufactured key
        would be worse. It is recorded in `unidentified` -- with the reason --
        so the refusal is visible rather than silent.

        CONSEQUENCE, STATED PLAINLY: as of CAUSAL-OCCURRENCE-IDENTITY-1A the
        whole protected-swing family (Category B) has no certified causal
        identity, so a v2 path refuses ALL of it and therefore holds no
        load-bearing structure, no ladder and no violation. A v2 path is
        CAPABILITY UNDER TEST, not a second opinion about the market, and it is
        not equivalent to v1 until 1B restores Category B. Production is v1.
        """
        v2 = self.causal_identity_version == CAUSAL_IDENTITY_V2
        for ev in occurrences or []:
            key = identity_of(ev, self.causal_identity_version)
            if v2 and not key:
                self.unidentified.append(
                    {"event_type": ev.get("event_type"),
                     "source_tf": ev.get("source_tf"),
                     "observed_at": ev.get("observed_at") or ev.get("event_time"),
                     "reason": refusal_reason(ev)})
                continue
            if key and key in self._seen:
                continue
            if key:
                self._seen.add(key)
            self.events.append(ev)
            self._apply(ev)

    # ── the state machine ───────────────────────────────────────────────────
    def _apply(self, ev):
        et = ev.get("event_type")

        # 1. A REJECTED RAID OPENS A HYPOTHESIS, NEVER AN OWNERSHIP CLAIM.
        #    Publishing `owner=bearish, status=forming` told the Brain the
        #    market was owned while admitting nothing had established it. On the
        #    degraded 2026-08-10 archive -- sweeps present, ZERO structure
        #    breaks, ZERO protected registrations -- that produced
        #    `owner=bearish` for all 116 scans of a session mechanics could not
        #    read at all.
        if et == LIQUIDITY_SWEEP:
            implied = RAID_IMPLIES.get(ev.get("sweep_direction"))
            if implied and self._leg_direction() is None:
                self.forming_direction, self.status = implied, "forming"
                self.origin = dict(ev)
                self.progression_tfs, self.ladder = set(), []
                self.adverse_replacements = []
                return
            if implied and implied != self._leg_direction() and self._leg_direction():
                # Counter-evidence. A flip requires the incumbent leg to DIE.
                ev["_counter_origin"] = True

        # 2. LOAD-BEARING STRUCTURE. TWO SEPARATE QUESTIONS:
        #      "has the path STRENGTHENED?"          -> favourable ratchet
        #      "what does it CURRENTLY rest on?"     -> the producer's answer
        #    Conflating them created a ghost: an adverse replacement was
        #    rejected as "not better", so the reference stayed pinned to
        #    29299.00 after the tracker had replaced it with 29321.00 --
        #    asserting `intact: True` about a level its own producer had
        #    stopped holding. Because the kill rule matches on level equality,
        #    the violation of 29321.00 could never kill the leg, and 2026-08-21
        #    replayed 153/153 bearish with zero releases.
        #
        #    NEVER PRESERVE A THESIS BY PRESERVING STALE FACTS.
        if et in (PROTECTED_SWING_REGISTERED, PROTECTED_SWING_REPLACED) \
                and self._leg_direction():
            if ev.get("side") == self._supporting_side() and ev.get("level") is not None:
                try:
                    lvl = float(ev["level"])
                except (TypeError, ValueError):
                    return
                cur = (self.load_bearing or {}).get("level")
                d = self._leg_direction()
                favourable = (cur is None
                              or (d == "bullish" and lvl >= cur)
                              or (d == "bearish" and lvl <= cur))
                self.load_bearing = {
                    "level": lvl, "side": ev.get("side"),
                    "timeframe": ev.get("source_tf"), "basis": ev.get("basis"),
                    "swing_id": ev.get("swing_id"), "at": ev.get("event_time"),
                    "intact": True, "producer_backed": True,
                    "last_move_favourable": bool(favourable)}
                if favourable:
                    if not self.ladder or self.ladder[-1] != lvl:
                        self.ladder.append(lvl)
                else:
                    self.adverse_replacements.append(
                        {"at": ev.get("event_time"), "from": cur, "to": lvl,
                         "timeframe": ev.get("source_tf")})
            return

        # 3. CONFIRMATION -- the hypothesis becomes an ESTABLISHED owner here,
        #    and only here: causal origin PLUS structural progression.
        if et == STRUCTURE_BREAK and self._leg_direction():
            if ev.get("direction") == self._leg_direction():
                self.progression_tfs.add(ev.get("source_tf"))
                if self.forming_direction:
                    self.owner, self.forming_direction = self.forming_direction, None
                if self.status in ("forming", "contested"):
                    self.status = "active"
            return

        # 4. LOAD-BEARING FAILURE -- the one event that kills a leg. Death
        #    RELEASES ownership; a leg's corpse does not keep owning the market.
        if et == PROTECTED_SWING_VIOLATED and self.load_bearing:
            same_side = ev.get("side") == self._supporting_side()
            try:
                hit = float(ev.get("level")) == self.load_bearing["level"]
            except (TypeError, ValueError):
                hit = False
            if same_side and hit:
                self.last_invalidated = {"owner": self._leg_direction(),
                                         "at": ev.get("event_time"),
                                         "level": self.load_bearing["level"]}
                self.releases.append(dict(self.last_invalidated))
                self.owner, self.forming_direction = "none", None
                self.status = "none"
                self.origin, self.load_bearing = None, None
                self.progression_tfs, self.ladder = set(), []
                self.adverse_replacements = []

    # ── derived views ───────────────────────────────────────────────────────
    def last_confirmation_time(self):
        stamps = [e.get("event_time") for e in self.events
                  if e.get("event_type") == STRUCTURE_BREAK
                  and e.get("direction") == self._leg_direction()]
        if self.load_bearing:
            stamps.append(self.load_bearing.get("at"))
        if self.origin:
            stamps.append(self.origin.get("event_time"))
        stamps = [s for s in stamps if s]
        return max(stamps) if stamps else ""

    def transfer_evidence(self):
        """AFFIRMATIVE evidence against the leg SINCE ITS LAST CONFIRMATION.
        Named booleans; never counted, never summed. Anchoring at the origin
        instead made every flag permanently sticky -- a counter-raid at 09:17
        still read as live counter-evidence at 11:51, so a leg was born
        contested and stayed contested however often it re-proved itself."""
        d = self._leg_direction()
        if not d:
            return {}
        opp = OPPOSITE[d]
        anchor = self.last_confirmation_time()
        after = [e for e in self.events if (e.get("event_time") or "") > anchor]
        return {
            "opposing_structure_break": any(
                e.get("event_type") == STRUCTURE_BREAK and e.get("direction") == opp
                for e in after),
            "load_bearing_failure": bool(self.load_bearing
                                         and not self.load_bearing.get("intact", True)),
            "load_bearing_replaced_against_path": any(
                (a.get("at") or "") > anchor for a in self.adverse_replacements),
            "opposing_raid_rejected": any(e.get("_counter_origin") for e in after),
            # TRUTHFUL NULLS. `false` would be a claim the producer cannot back.
            "opposing_market_structure_shift": None,
            "opposing_displacement": None,
        }

    def resolve_status(self):
        """OWNER and HEALTH are separate. A leg may be owned and unwell.

        RULE A (operator ruling, 2026-08-24): a rejected opposing raid alone is
        counter-evidence, NOT a contest -- counter-path liquidity behaviour is
        ordinary inside a retracement. Substantive adverse structure is what
        moves an established path to `contested`.
        """
        if self.owner == "none":
            return "forming" if self.forming_direction else "none"
        te = self.transfer_evidence()
        if te.get("load_bearing_failure"):
            return "invalidated"
        if te.get("opposing_structure_break") or \
                te.get("load_bearing_replaced_against_path"):
            return "contested"
        return "active"

    def state(self, *, available: bool = True, unavailable_reason: str = None) -> dict:
        """The compact block published to the Brain. ~215 tokens."""
        if not available:
            return {"state_available": False,
                    "unavailable_reason": unavailable_reason or STATE_UNAVAILABLE,
                    "owner": None, "status": None, "forming_direction": None}
        d = self._leg_direction()
        prog = sorted(self.progression_tfs, key=lambda t: TF_RESOLUTION.get(t, 0))
        return {
            "state_available": True,
            "unavailable_reason": None,
            "owner": self.owner,
            "forming_direction": self.forming_direction,
            "status": self.resolve_status(),
            "origin": None if not self.origin else {
                "event": ("sell_side_raid_rejected" if d == "bullish"
                          else "buy_side_raid_rejected"),
                "at": self.origin.get("event_time"),
                "source_tf": self.origin.get("source_tf"),
                "occurrence_id": self.origin.get("occurrence_id")},
            "load_bearing_structure": self.load_bearing,
            "progression": {
                "supporting_timeframes": prog,
                "highest_confirmed": prog[-1] if prog else None,
                "favourable_ladder": list(self.ladder),
                "successive_favourable": len(self.ladder) > 1},
            "adverse_replacements": list(self.adverse_replacements[-3:]),
            "transfer_evidence": self.transfer_evidence(),
            "last_invalidated": self.last_invalidated,
            "ownership_changed_this_scan": self.owner != self._prev_owner,
            "session": self._session_key,
            "last_reset_reason": self.last_reset_reason,
            "notes": {"opposing_market_structure_shift": MSS_HAS_NO_DIRECTION},
        }

    def mark_scan_end(self):
        self._prev_owner = self.owner
