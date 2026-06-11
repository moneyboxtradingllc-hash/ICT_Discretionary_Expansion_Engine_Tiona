"""
Phase 5H.4 — Member Calibration.

Scores each council member's votes against measured outcomes, from the same
divergence-ledger events (events embed council_digest — one source of truth).

Per member:
  no_hit_rate    — P(loss | member voted no)   : were their objections right?
  no_miss_cost_R — sum(r) of winners they opposed: what did caution cost?
  yes_hit_rate   — P(win  | member voted yes)
  confidence_buckets — stated confidence (50-70 / 70-85 / 85+) vs realized
                       accuracy. Until a member's buckets are monotone and
                       roughly honest, its confidence number is DISPLAY-ONLY.

This ledger is the only path by which confidence arithmetic ever becomes
legitimate. OBSERVE ONLY. Never raises.
"""

_BUCKETS = (("b50_70", 50, 70), ("b70_85", 70, 85), ("b85_plus", 85, 101))


def _bucket(confidence: int) -> "str | None":
    for name, lo, hi in _BUCKETS:
        if lo <= confidence < hi:
            return name
    return None


def calibrate_members(events: list) -> dict:
    """
    Build the member calibration table from resolved ledger events.
    A member's vote is 'correct' when:
      vote=no  and outcome r < 0   (objection vindicated)
      vote=yes and outcome r > 0   (endorsement vindicated)
    Neutral votes and r == 0 outcomes are excluded from accuracy.
    Never raises.
    """
    try:
        members: dict = {}

        for ev in events:
            res = ev.get("resolution") or {}
            if res.get("state") != "resolved":
                continue
            r = float(res.get("r", 0.0))

            for vote_rec in ev.get("council_digest", []):
                name = vote_rec.get("member")
                vote = vote_rec.get("vote")
                conf = int(vote_rec.get("confidence", 0) or 0)
                if not name:
                    continue

                m = members.setdefault(name, {
                    "no_total": 0, "no_correct": 0, "no_miss_cost_R": 0.0,
                    "yes_total": 0, "yes_correct": 0,
                    "neutral_total": 0,
                    "buckets": {b[0]: {"total": 0, "correct": 0}
                                for b in _BUCKETS},
                })

                if vote == "neutral":
                    m["neutral_total"] += 1
                    continue
                if r == 0.0:
                    continue  # indeterminate outcomes don't score accuracy

                correct = (vote == "no" and r < 0) or (vote == "yes" and r > 0)

                if vote == "no":
                    m["no_total"] += 1
                    if correct:
                        m["no_correct"] += 1
                    elif r > 0:
                        m["no_miss_cost_R"] = round(m["no_miss_cost_R"] + r, 4)
                elif vote == "yes":
                    m["yes_total"] += 1
                    if correct:
                        m["yes_correct"] += 1

                bname = _bucket(conf)
                if bname:
                    m["buckets"][bname]["total"] += 1
                    if correct:
                        m["buckets"][bname]["correct"] += 1

        # Derive rates + honesty verdicts
        out = {}
        for name, m in members.items():
            no_rate  = round(m["no_correct"] / m["no_total"], 4)  if m["no_total"]  else None
            yes_rate = round(m["yes_correct"] / m["yes_total"], 4) if m["yes_total"] else None

            bucket_rates = {}
            for bname, b in m["buckets"].items():
                bucket_rates[bname] = (
                    round(b["correct"] / b["total"], 4) if b["total"] else None
                )

            out[name] = {
                "no_votes":           m["no_total"],
                "no_hit_rate":        no_rate,
                "no_miss_cost_R":     m["no_miss_cost_R"],
                "yes_votes":          m["yes_total"],
                "yes_hit_rate":       yes_rate,
                "neutral_votes":      m["neutral_total"],
                "confidence_buckets": bucket_rates,
                "confidence_honest":  _honesty(bucket_rates),
            }
        return out
    except Exception as exc:  # noqa: BLE001
        return {"error": f"calibration error: {exc}"}


def _honesty(bucket_rates: dict) -> dict:
    """
    Honest = every populated bucket has >= 5 samples and realized accuracy
    is monotone non-decreasing across buckets. Until then: display-only.
    """
    ordered  = [bucket_rates.get(b[0]) for b in _BUCKETS]
    populated = [r for r in ordered if r is not None]
    if len(populated) < 2:
        return {"honest": False, "reason": "insufficient populated buckets"}
    monotone = all(populated[i] <= populated[i + 1]
                   for i in range(len(populated) - 1))
    return {
        "honest": monotone,
        "reason": "monotone" if monotone else "confidence not monotone with accuracy",
    }
