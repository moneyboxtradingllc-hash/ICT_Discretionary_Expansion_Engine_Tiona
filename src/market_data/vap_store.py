"""VAP STORE — durable minute x tick observed volume. Append-only.

LUNA-VAP-CAPTURE-AND-PERSISTENCE-1 (2026-08-30).

WHAT IS RECORDED, IN THE ONLY WORDS THAT ARE TRUE. The feed carries no venue
trade id and no sequence number, and reconnect/restart delivery cannot be proven
exactly-once. So this store holds OBSERVED TRADED VOLUME AT PRICE -- what this
capture process received -- and never claims exact exchange volume. Every
consumer inherits that ceiling; none may quietly raise it.

TWO ORTHOGONAL AXES, NEVER COLLAPSED.

    status                   how well the MINUTE was observed
                             COMPLETE / PARTIAL_START / INTERRUPTED / UNPROVEN
    observed_zero_volume     a claim about VOLUME, only ever made under COMPLETE

`COMPLETE` is a capture-continuity verdict. It does NOT mean the exchange
printed nothing else; it means this process watched an expected minute end to
end on one unbroken connection and received what it received. Collapsing those
two axes into one field is how "we saw nothing" becomes "nothing happened".

ABSENCE IS NOT ZERO. A minute with no row is a minute with no evidence. Only a
positively established observed-zero minute is written as zero, and the flag
saying so is explicit rather than inferred from an empty level map.

DURABILITY FOLLOWS THE JOURNAL, NOT THE CANDLE STORE. `break_even_journal` and
`topstepx_submission_record` write-flush-fsync and RETURN whether the bytes
landed; the 1m candle jsonl does not fsync at all. A minute that cannot be
proven durable must not be reported as durably sealed, so this store returns a
boolean and its caller is expected to read it.

KEYED BY CONTRACT ID, NEVER BY SYMBOL. Price is discontinuous across a futures
roll: merging CON.F.US.MNQ.U26 with its successor would place volume at prices
the new contract never traded. `htf_accum` already records this hazard for
multi-day memory; here it is enforced by the file name.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

SCHEMA = "vap_minute.v1"

# ── capture-continuity status (about the MINUTE, not about the volume) ───────
COMPLETE = "COMPLETE"              # expected minute, watched end to end, one generation
PARTIAL_START = "PARTIAL_START"    # capture attached after the minute had begun
INTERRUPTED = "INTERRUPTED"        # the connection generation changed mid-minute
UNPROVEN = "UNPROVEN"              # continuity or venue cadence could not be established

STATUSES = (COMPLETE, PARTIAL_START, INTERRUPTED, UNPROVEN)

#: Statuses under which an observed-zero VOLUME claim may be made at all.
#: PARTIAL_START and INTERRUPTED saw only part of the minute, so their silence
#: proves nothing; UNPROVEN could not even establish the minute was tradable.
_ZERO_CLAIMABLE = (COMPLETE,)

#: OWNER POLICY (2026-08-30). Roughly six months of irreplaceable evidence at a
#: measured 3-6 MB/day. Not a tuning knob: shortening it destroys history that
#: cannot be re-derived from any source, because OHLCV carries no price
#: attribution and no venue trade-history endpoint is wired.
VAP_RETENTION_DAYS = 180


def _num(v):
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def store_path(store_dir: str, contract_id: str) -> str:
    """One file per CONTRACT. A roll gets its own identity, never a merge."""
    safe = str(contract_id or "unknown").replace(".", "_").replace(os.sep, "_")
    return os.path.join(store_dir, f"vap_{safe}.jsonl")


def build_record(*, contract_id, minute, status, tick_size, levels=None,
                 raw_type_volume=None, unknown_type_volume=0.0,
                 trades_observed=0, connection_generation=None,
                 observed_zero_volume=False, sealed_at=None) -> dict:
    """One minute's evidence, in the store's exact published shape.

    `levels` maps INTEGER TICK INDEX -> observed volume. JSON has no integer
    keys, so they serialize as strings and `load` converts them back; the
    identity is the integer either way and no float ever becomes a key.
    """
    lv = {}
    for k, v in (levels or {}).items():
        vol = _num(v)
        if vol is None:
            continue
        try:
            lv[str(int(k))] = vol
        except (TypeError, ValueError):
            continue
    total = round(sum(lv.values()), 6)
    raw = {}
    for k, v in (raw_type_volume or {}).items():
        vol = _num(v)
        if vol is not None:
            raw[str(k)] = vol
    zero = bool(observed_zero_volume) and status in _ZERO_CLAIMABLE and total == 0
    return {
        "schema": SCHEMA,
        "contract_id": str(contract_id),
        "minute": str(minute),
        "status": status if status in STATUSES else UNPROVEN,
        "tick_size": _num(tick_size),
        "levels": lv,
        "total_observed_volume": total,
        # THE CLAIM, SPELLED OUT WHERE SERIALIZATION CANNOT LOSE IT.
        "observed_zero_volume": zero,
        "volume_claim": ("observed_zero_volume" if zero else "total_observed_volume"),
        "claim_note": ("volume this capture process OBSERVED at each price; the "
                       "feed carries no trade id or sequence number, so this is "
                       "never a claim of exact exchange volume"),
        # Raw side evidence, uninterpreted on purpose. No BUY/SELL vocabulary
        # enters this layer: the vendor documents `type` as a side code but our
        # own tape has never been sampled, so the code is preserved and nothing
        # is labelled. A missing code becomes `unknown`, never a default.
        "raw_type_volume": raw,
        "unknown_type_volume": _num(unknown_type_volume) or 0.0,
        "trades_observed": int(trades_observed or 0),
        "connection_generation": connection_generation,
        "sealed_at": sealed_at or datetime.now(timezone.utc).isoformat(),
    }


def append(store_dir: str, record: dict) -> bool:
    """Append one sealed minute. Returns whether the bytes reached disk.

    THE BOOLEAN IS LOAD-BEARING. A minute whose write failed has not been
    durably sealed and the caller must not treat it as recorded -- the same law
    the break-even journal established for a write-ahead intent.
    """
    try:
        path = store_path(store_dir, record.get("contract_id"))
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return True
    except Exception:  # noqa: BLE001 — a store failure is never an exception
        return False


def load(store_dir: str, contract_id: str, *, since=None) -> list:
    """Every sealed minute for this contract, oldest first.

    A malformed line is skipped rather than fatal: a torn final write is the
    expected shape of a crash during append, and one bad line must not cost the
    history in front of it.
    """
    path = store_path(store_dir, contract_id)
    out = []
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(row, dict) or row.get("schema") != SCHEMA:
                    continue
                if since is not None and str(row.get("minute") or "") < str(since):
                    continue
                lv = row.get("levels")
                if isinstance(lv, dict):
                    keyed = {}
                    for k, v in lv.items():
                        try:
                            keyed[int(k)] = _num(v) or 0.0
                        except (TypeError, ValueError):
                            continue
                    row["levels"] = keyed
                out.append(row)
    except Exception:  # noqa: BLE001
        return out
    out.sort(key=lambda r: str(r.get("minute") or ""))
    return out


def sealed_minutes(store_dir: str, contract_id: str) -> set:
    """The minute identities already on disk. Restart reads this to avoid
    re-sealing history it already holds."""
    return {str(r.get("minute")) for r in load(store_dir, contract_id)}


def prune(store_dir: str, contract_id: str, *,
          retention_days: int = VAP_RETENTION_DAYS, now=None) -> dict:
    """Drop minutes older than the horizon. Survivors are copied VERBATIM.

    A pruner that rewrote a record -- recomputing a total, upgrading a status,
    normalising a claim -- would let retention become a second producer of
    evidence. Surviving lines are re-serialized from what was read and nothing
    else, so pruning can only ever remove.

    Returns counts; never raises. A failure leaves the file untouched.
    """
    result = {"kept": 0, "dropped": 0, "ok": False, "error": None,
              "retention_days": int(retention_days)}
    try:
        path = store_path(store_dir, contract_id)
        if not os.path.exists(path):
            result["ok"] = True
            return result
        moment = now or datetime.now(timezone.utc)
        if isinstance(moment, str):
            moment = datetime.fromisoformat(moment.replace("Z", "+00:00"))
        horizon = moment - timedelta(days=int(retention_days))
        kept = []
        for row in load(store_dir, contract_id):
            try:
                when = datetime.fromisoformat(str(row["minute"]).replace("Z", "+00:00"))
            except Exception:  # noqa: BLE001 — an unparseable minute is never dropped
                kept.append(row)
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when < horizon:
                result["dropped"] += 1
            else:
                kept.append(row)
        if not result["dropped"]:
            result["kept"] = len(kept)
            result["ok"] = True
            return result
        tmp = path + ".pruning"
        with open(tmp, "w", encoding="utf-8") as fh:
            for row in kept:
                row = dict(row)
                lv = row.get("levels")
                if isinstance(lv, dict):
                    row["levels"] = {str(k): v for k, v in lv.items()}
                fh.write(json.dumps(row, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        result["kept"] = len(kept)
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result
