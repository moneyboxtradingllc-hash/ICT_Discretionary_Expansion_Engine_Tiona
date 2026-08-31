"""Read an archived session and cut it into descriptive segments.

BUILD-SAFE-DESCRIPTIVE-SESSION-MEMORY (2026-08-06).

One record per scan would store 172 near-identical observations of a quiet
Thursday and then retrieve them as 172 votes for the same thing. Segmentation is
what makes the corpus a description of a SESSION rather than a transcript of a
loop.

The law, in order:

  1. QUALITY   -- a scan that was degraded, fell back, was malformed, came from
                  an unsanctioned model, or is not this instrument does not
                  contribute at all. It is counted as an exclusion, not fixed.
  2. SIGNATURE -- consecutive scans sharing a state signature are one run.
  3. DURATION  -- a run shorter than MIN_SEGMENT_SCANS is a fluctuation, not a
                  state. It is absorbed into its neighbour; its scans still
                  count toward the distributions, so the blip stays visible in
                  the record without becoming its own durable truth.
  4. CEILING   -- if that still yields more than SEGMENT_CEILING segments, the
                  signature coarsens one rung down a FIXED ladder and the cut is
                  redone. Segments are never truncated: dropping the tail of a
                  session would silently delete the afternoon.

The ceiling is a storage bound, not a target. A quiet session may produce three.
"""
from __future__ import annotations

import collections
import hashlib
import json
import os

from ai_brain.production_model import (FORBIDDEN_MODELS, PREVIOUS_PRODUCTION_MODEL,
                                       PRODUCTION_MODEL)
from ai_retrieval import embedding_v2 as EV2
from doctrine.instrument_identity import PRODUCTION_INSTRUMENT

SEGMENT_CEILING = 12
MIN_SEGMENT_SCANS = 5

#: Models whose reads may become durable memory.
#:
#: NOT simply `PRODUCTION_MODEL`. PROD-20260806 ran gpt-5.6-luna, which was the
#: sanctioned production model that day and is now the PREVIOUS one. A filter
#: pinned to the current model would make every past session unlearnable the
#: moment the Brain is upgraded -- and would have made this mission's own dry
#: run vacuous. What must never contribute is an UNSANCTIONED model: a forbidden
#: alias, an ad-hoc override, or a fallback. Every record stores `source_model`
#: verbatim, so a consumer can always narrow further.
SANCTIONED_MEMORY_MODELS = frozenset({PRODUCTION_MODEL, PREVIOUS_PRODUCTION_MODEL})

#: Finest to coarsest. The first tier that fits the ceiling wins.
SIGNATURE_TIERS = (
    ("T0", ("session_phase", "market_regime", "volatility_state",
            "delivery_state", "narrative_direction", "narrative_phase",
            "draw_present", "protected_state")),
    ("T1", ("session_phase", "market_regime", "delivery_state",
            "narrative_direction", "narrative_phase", "draw_present")),
    ("T2", ("session_phase", "market_regime", "narrative_direction",
            "narrative_phase")),
    ("T3", ("session_phase", "market_regime", "narrative_direction")),
    ("T4", ("session_phase", "narrative_direction")),
    ("T5", ("session_phase",)),
)

_ACTION_TOKENS = ("stand_down", "prepare_bullish", "prepare_bearish",
                  "prepare_long", "prepare_short", "monitor", "wait")


class SessionSourceError(RuntimeError):
    """The session source cannot be read as authoritative evidence."""


# ── normalisation ────────────────────────────────────────────────────────────
def normalize_action(value) -> str:
    """A categorical action token. Never the model's prose.

    PROD-20260806 shows why: 70 scans emitted the token `stand_down` and 27 more
    emitted whole paragraphs that MEAN stand down. Storing the paragraph would
    put unbounded model narration into durable memory -- exactly where the
    language law is hardest to enforce and where a stray "avoided" would slip
    through. The prose is reduced to a token or to `other`; the prose itself is
    never stored.
    """
    if not isinstance(value, str) or not value.strip():
        return "unknown"
    text = value.strip().lower()
    if text in _ACTION_TOKENS:
        return text
    collapsed = text.replace("-", " ").replace("_", " ")
    if collapsed.startswith("stand down") or " stand down" in collapsed[:40]:
        return "stand_down"
    if collapsed.startswith("remain flat") or collapsed.startswith("stay flat"):
        return "stand_down"
    if collapsed.startswith("prepare"):
        if "bear" in collapsed[:40] or "short" in collapsed[:40]:
            return "prepare_bearish"
        if "bull" in collapsed[:40] or "long" in collapsed[:40]:
            return "prepare_bullish"
    if collapsed.startswith("monitor") or collapsed.startswith("wait"):
        return "monitor"
    return "other"


def _protected_state(swings: dict) -> str:
    s = swings or {}
    return f"{s.get('protected_high_status') or 'none'}/{s.get('protected_low_status') or 'none'}"


def _structure_state(witness: dict) -> str:
    """Display label for the structure WITNESS. Never directional.

    V2: this string is METADATA ONLY. The vector reads the underlying
    bos_event/mss_event flags through `embedding_v2.structure_evidence`, so
    there is no display string to parse and no unparseable string that could
    silently be read as "quiet".
    """
    try:
        ev = EV2.structure_evidence(witness)
    except EV2.EmbeddingError:
        return "witness_unavailable"
    if ev["quiet"]:
        return "witness_quiet"
    return f"witness_bos_{ev['bos_count']}_mss_{ev['mss_count']}"


def _protected_level(block) -> dict:
    """Normalise a protected swing to ONE shape, always the same keys.

    v1 stored whatever the producer emitted: `null` for nine records and a
    nested dict for the tenth, under the same schema field. A consumer then has
    to type-check every read, which is how a level eventually gets compared to a
    price by accident.
    """
    b = block if isinstance(block, dict) else {}
    return {"level": b.get("level"), "timeframe": b.get("timeframe"),
            "basis": b.get("basis"), "registered_at": b.get("registered_at")}


# ── reading an archived session ──────────────────────────────────────────────
def load_session_observations(archive_path: str) -> dict:
    """Read the archive into per-scan observations plus exclusion counts.

    Reads ONLY final historical fact: the inputs the Brain saw and the outputs
    it produced. Nothing is re-run and no current-code interpretation is applied
    to a historical scan.
    """
    scans_dir = os.path.join(archive_path, "scans", "inputs")
    parsed_dir = os.path.join(archive_path, "brain", "parsed_outputs")
    full_dir = os.path.join(archive_path, "brain", "full_artifacts")
    index_path = os.path.join(archive_path, "scans", "scan_index.json")
    for path in (scans_dir, parsed_dir, full_dir, index_path):
        if not os.path.exists(path):
            raise SessionSourceError(f"archive incomplete: missing {path}")

    index = json.load(open(index_path, encoding="utf-8"))
    by_et = {row.get("et"): row for row in index.get("scans", [])}

    observations, excluded = [], collections.Counter()
    names = sorted(n for n in os.listdir(scans_dir) if n.endswith(".json"))
    for name in names:
        try:
            inp = json.load(open(os.path.join(scans_dir, name), encoding="utf-8"))
            parsed = json.load(open(os.path.join(parsed_dir, name), encoding="utf-8"))
            full = json.load(open(os.path.join(full_dir, name), encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            excluded["unreadable_artifact"] += 1
            continue

        stamp = name.rsplit("_", 1)[0]               # 20260806_093024
        et = f"{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}"
        meta = by_et.get(et, {})

        instrument = (meta.get("instrument") or full.get("symbol") or "").upper()
        contract = meta.get("contract") or ""
        model = full.get("llm_model")

        if instrument != PRODUCTION_INSTRUMENT:
            excluded["foreign_or_missing_instrument"] += 1
            continue
        if not contract:
            excluded["missing_contract_identity"] += 1
            continue
        if full.get("source") != "llm":
            excluded[f"source_{full.get('source') or 'unknown'}"] += 1
            continue
        if full.get("fallback_reason"):
            excluded["fallback"] += 1
            continue
        # SANCTIONED is checked FIRST, deliberately. Luna appears in
        # FORBIDDEN_MODELS because it may not be RUN today -- a live-execution
        # question. Whether a read Luna produced on the day it WAS the
        # production model may be DESCRIBED is a different question, and
        # answering it with the execution list would have excluded all 167
        # eligible PROD-20260806 scans and made this mechanism vacuous.
        if model not in SANCTIONED_MEMORY_MODELS:
            excluded["forbidden_model" if model in FORBIDDEN_MODELS
                     else "unsanctioned_model"] += 1
            continue
        if not isinstance(parsed, dict) or not parsed.get("narrative_direction"):
            excluded["malformed_parsed_output"] += 1
            continue
        if full.get("test_artifact") or inp.get("test_artifact"):
            excluded["test_artifact"] += 1
            continue

        liq = inp.get("liquidity") or {}
        swings = inp.get("protected_swings") or {}
        vol = (((inp.get("adaptive_policy_context") or {}).get("dimensions")
                or {}).get("volatility") or {})
        observations.append({
            "artifact_id": name,
            "et": et,
            "code_phase": meta.get("phase"),
            "instrument": instrument,
            "contract": contract,
            "source_model": model,
            "market_timestamp": meta.get("market_timestamp")
                                or inp.get("timestamp"),
            "session_phase": inp.get("session") or "unknown",
            "market_regime": (inp.get("governance_context") or {}).get("regime")
                             or "unknown",
            "volatility_state": vol.get("key") or "unknown",
            "delivery_state": (inp.get("delivery") or {}).get("state") or "unknown",
            "narrative_direction": parsed.get("narrative_direction") or "unknown",
            "narrative_phase": parsed.get("narrative_phase") or "unknown",
            "phase_confidence": parsed.get("phase_confidence"),
            "action": normalize_action(parsed.get("current_action")),
            "draw_present": bool(liq.get("active_draw")),
            "exhaustion_present": (inp.get("delivery") or {}).get("exhaustion_present"),
            "protected_state": _protected_state(swings),
            "protected_high": _protected_level(swings.get("protected_high")),
            "protected_low": _protected_level(swings.get("protected_low")),
            # Authoritative underlying evidence -- the vector reads THESE.
            "structure_witness": inp.get("STRUCTURE_WITNESS"),
            "structure_state": _structure_state(inp.get("STRUCTURE_WITNESS")),
            "nearest_buy_side": liq.get("nearest_buy_side"),
            "nearest_sell_side": liq.get("nearest_sell_side"),
            "liquidity_state": EV2.liquidity_state(liq.get("nearest_buy_side"),
                                                   liq.get("nearest_sell_side")),
        })

    return {"observations": observations, "excluded": dict(excluded),
            "total_scans": len(names), "session_id": index.get("session")}


# ── the cut ──────────────────────────────────────────────────────────────────
def _runs(observations: list, keys: tuple) -> list:
    runs = []
    for obs in observations:
        sig = tuple(obs.get(k) for k in keys)
        if runs and runs[-1]["signature"] == sig:
            runs[-1]["scans"].append(obs)
        else:
            runs.append({"signature": sig, "keys": keys, "scans": [obs]})
    return runs


def _absorb_short_runs(runs: list, minimum: int) -> list:
    """A run shorter than `minimum` joins a neighbour, keeping the neighbour's
    signature. A LEADING short run joins the run after it -- there is nothing
    before the open to absorb it, and leaving it standing would let the first
    two minutes of the session become a durable state of its own."""
    if not runs:
        return []
    out = []
    pending = []
    for run in runs:
        if len(run["scans"]) < minimum and out:
            out[-1]["scans"].extend(run["scans"])
        elif len(run["scans"]) < minimum:
            pending.extend(run["scans"])
        else:
            if pending:
                run = dict(run, scans=pending + run["scans"])
                pending = []
            # RE-JOIN across an absorbed blip. Without this, one off-signature
            # scan in the middle of a homogeneous stretch splits it into two
            # segments with IDENTICAL signatures -- the blip is discarded from
            # the signature but still leaves a permanent seam, so the corpus
            # stores the same state twice and retrieval returns it twice. This
            # is visible in the PROD-20260806 cut: two lunch segments that
            # differed in nothing the signature reads.
            if out and out[-1]["signature"] == run["signature"]:
                out[-1]["scans"].extend(run["scans"])
            else:
                out.append(dict(run, scans=list(run["scans"])))
    if pending:                      # the whole session was below the minimum
        out.append({"signature": runs[0]["signature"], "keys": runs[0]["keys"],
                    "scans": pending})
    return out


def cut_segments(observations: list, *, ceiling: int = SEGMENT_CEILING,
                 minimum: int = MIN_SEGMENT_SCANS) -> dict:
    """Segment the session. Returns the chosen tier and the segments."""
    if not observations:
        return {"tier": None, "segments": [], "reason": "no_eligible_observations"}
    for label, keys in SIGNATURE_TIERS:
        segments = _absorb_short_runs(_runs(observations, keys), minimum)
        if len(segments) <= ceiling:
            return {"tier": label, "tier_keys": keys, "segments": segments,
                    "raw_runs": len(_runs(observations, keys))}
    label, keys = SIGNATURE_TIERS[-1]
    segments = _absorb_short_runs(_runs(observations, keys), minimum)
    return {"tier": label, "tier_keys": keys, "segments": segments,
            "raw_runs": len(_runs(observations, keys))}


# ── segment -> descriptive fields ────────────────────────────────────────────
def _dominant(values: list) -> str:
    """Most frequent value; ties broken alphabetically so it is deterministic."""
    counts = collections.Counter(v for v in values if v)
    if not counts:
        return "unknown"
    top = max(counts.values())
    return sorted(k for k, v in counts.items() if v == top)[0]


def _confidence_summary(values: list) -> dict:
    nums = []
    for v in values:
        try:
            nums.append(float(v))
        except (TypeError, ValueError):
            continue
    if not nums:
        return {"observations": 0}
    return {"observations": len(nums), "min": min(nums), "max": max(nums),
            "mean": round(sum(nums) / len(nums), 2)}


def no_candidate_reasons(segment_scans: list, candidate_count: int) -> list:
    """What was ABSENT, stated mechanically. Never why that was wise."""
    if candidate_count:
        return []
    reasons = []
    actions = [s["action"] for s in segment_scans]
    directions = [s["narrative_direction"] for s in segment_scans]
    if _dominant(actions) == "stand_down":
        reasons.append("action_declines_entry")
    if _dominant(directions) in ("conflicted", "neutral", "unknown"):
        reasons.append("direction_not_established")
    if all(s["protected_state"] == "none/none" for s in segment_scans):
        reasons.append("no_protected_structure")
    if not any(s["draw_present"] for s in segment_scans):
        reasons.append("no_active_draw")
    return reasons or ["no_stated_reason_recorded"]


def segment_digest(segment_scans: list) -> str:
    """Identity of the source artifacts this segment was read from."""
    h = hashlib.sha256()
    for scan in segment_scans:
        h.update(scan["artifact_id"].encode("utf-8"))
    return h.hexdigest()[:24]
