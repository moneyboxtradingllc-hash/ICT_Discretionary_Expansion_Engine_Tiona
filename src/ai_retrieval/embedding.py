"""
Phase AB-3 — Market-state embedding.

Real vector embedding over MARKET STATE, not categorical label overlap. Each
record/context maps to a fixed-dimension numeric vector (one-hot categoricals +
normalized scalars); similarity is cosine over those vectors. The retrieval key
is the narrative/delivery/liquidity/protected-swing state — not entry-model
labels (Requirement 5).

Deterministic, dependency-light (numpy for the dot product). Never raises.
"""
import numpy as np

# Fixed, ordered categorical vocabularies → stable vector layout.
_REGIMES = ["range_rotation", "chop", "trend_up", "trend_down",
            "expansion_up", "expansion_down", "reversal_attempt",
            "high_volatility", "low_volatility", "unknown"]
_VOL = ["stable", "unstable", "toxic", "explosive", "liquidity_vacuum", "unknown"]
_PHASES = ["accumulation", "manipulation", "distribution", "reversal",
           "continuation", "exhaustion", "transition", "unknown"]
_DIRS = ["bullish", "bearish", "conflicted", "neutral", "none"]
_SESSIONS = ["ny_open", "morning_continuation", "lunch", "afternoon",
             "premarket", "after_hours", "unknown"]


def _onehot(value, vocab):
    v = (value or "unknown")
    v = v if isinstance(v, str) else "unknown"
    v = v.lower()
    return [1.0 if v == item else 0.0 for item in vocab]


def _key_fields(rec_or_ctx: dict) -> dict:
    """Pull the narrative/delivery/liquidity/protected key fields from either a
    memory record or a live snapshot-shaped dict."""
    if "narrative_context" in rec_or_ctx:   # memory record
        mc = rec_or_ctx.get("market_context", {}) or {}
        nc = rec_or_ctx.get("narrative_context", {}) or {}
        return {
            "regime": mc.get("regime"), "vol": mc.get("volatility_state"),
            "session": mc.get("session"),
            "ndir": nc.get("narrative_direction"),
            "nphase": nc.get("narrative_phase"),
            "ddir": nc.get("delivery_direction"),
            "draw": nc.get("active_liquidity_draw"),
            "ph": nc.get("protected_high"), "pl": nc.get("protected_low"),
            "nconf": None, "dconf": None, "exhaustion": None,
        }
    # live snapshot
    mr = rec_or_ctx.get("market_regime", {}) or {}
    na = rec_or_ctx.get("narrative_authority", {}) or {}
    sc = rec_or_ctx.get("shared_context", {}) or {}
    ps = rec_or_ctx.get("protected_swings", {}) or {}
    return {
        "regime": mr.get("regime_label"), "vol": mr.get("volatility_state"),
        "session": rec_or_ctx.get("session"),
        "ndir": na.get("narrative_direction"),
        "nphase": na.get("narrative_phase"),
        "ddir": sc.get("delivery_state"),
        "draw": na.get("active_liquidity_draw"),
        "ph": ps.get("protected_high"), "pl": ps.get("protected_low"),
        "nconf": na.get("narrative_confidence"),
        "dconf": sc.get("delivery_confidence"),
        "exhaustion": sc.get("exhaustion_present"),
    }


def _norm_dir(d):
    """Normalize a delivery state like 'bearish_delivery' → 'bearish'."""
    if not d:
        return "none"
    d = str(d).lower()
    for k in ("bullish", "bearish", "conflicted", "neutral"):
        if d.startswith(k) or d == k:
            return k
    return "none"


def embed(rec_or_ctx: dict) -> list:
    """Return the fixed-dimension feature vector. Never raises."""
    try:
        f = _key_fields(rec_or_ctx)
        vec = []
        vec += _onehot(f["regime"], _REGIMES)
        vec += _onehot(f["vol"], _VOL)
        vec += _onehot(f["session"], _SESSIONS)
        vec += _onehot(f["nphase"], _PHASES)
        vec += _onehot(f["ndir"], _DIRS)
        vec += _onehot(_norm_dir(f["ddir"]), _DIRS)
        # scalars (0..1)
        def s01(v, d=0.0):
            try:
                return max(0.0, min(1.0, float(v) / 100.0))
            except (TypeError, ValueError):
                return d
        vec.append(s01(f["nconf"]))
        vec.append(s01(f["dconf"]))
        vec.append(1.0 if f["ph"] else 0.0)
        vec.append(1.0 if f["pl"] else 0.0)
        vec.append(1.0 if f["draw"] else 0.0)
        vec.append(1.0 if f["exhaustion"] else 0.0)
        return vec
    except Exception:  # noqa: BLE001
        # degrade to a zero vector of the correct dimension
        return [0.0] * EMBED_DIM


EMBED_DIM = (len(_REGIMES) + len(_VOL) + len(_SESSIONS) + len(_PHASES)
             + len(_DIRS) * 2 + 6)


def cosine(a: list, b: list) -> float:
    try:
        va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        na, nb = np.linalg.norm(va), np.linalg.norm(vb)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(va, vb) / (na * nb))
    except Exception:  # noqa: BLE001
        return 0.0
