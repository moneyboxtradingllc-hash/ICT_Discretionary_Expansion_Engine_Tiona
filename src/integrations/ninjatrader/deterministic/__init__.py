"""DETERMINISTIC_MNQ_SIM_ONLY — a mechanical, sim-only automated trading lane.

Author is `deterministic_sim_author` (explicit predicates only). This lane NEVER
calls the AI Brain / OpenAI and never claims mechanical authorship is AI
authorship. Every opportunity it records is labelled mode+author.

Frozen doctrine (this lane):
  * Account : DEMO8458533 (sim only)     * Instrument : MNQ SEP26
  * Sizing  : RISK-BASED — contracts = floor($500 / (stop_pts x $2)), capped at
              MAX_CONTRACTS. Tighter stop -> more size; wider stop -> less; the
              per-trade dollar risk is pinned near MAX_RISK_DOLLARS.
  * Target  : fixed 35.00 points from the actual average fill
  * Stop    : the setup's STRUCTURAL invalidation; HARD cap 25.00 points
              (wider than 25pt -> NO TRADE, never widened to fit)
  * Max simultaneous positions: 1   * Max trades/day: 2
  * Daily realized-loss ceiling: $1000 (gross-modeled pre-check)
  * Scale-in / pyramiding: FORBIDDEN

Risk basis: MNQ is $2/point/contract. Position size varies with the structural
stop so worst-case loss stays within MAX_RISK_DOLLARS ($500): e.g. 12pt->20,
16.5pt->15, 20pt->12, 25pt->10 contracts. Two trades/day => up to ~$1000 ceiling.
"""

MODE = "DETERMINISTIC_MNQ_SIM_ONLY"
AUTHOR = "deterministic_sim_author"
EVIDENCE_ERA = "MNQ_DETERMINISTIC_SIM_WEEK"

ACCOUNT = "DEMO8458533"
INSTRUMENT = "MNQ SEP26"

POINT_VALUE = 2.00              # $ per index point per contract (MNQ)
TICK_SIZE = 0.25

TARGET_POINTS = 35.00           # fixed profit distance
MAX_STOP_POINTS = 25.00         # HARD structural-stop cap (wider -> NO TRADE)
MAX_RISK_DOLLARS = 500.00       # per-trade risk budget; size scales to the stop
MAX_CONTRACTS = 30              # safety ceiling on the risk-sized contract count

MAX_TRADES_PER_DAY = 2
DAILY_LOSS_CEILING = 1000.00    # realized-loss ceiling ($) — fallback when equity unknown

# ── COMPOUNDING — risk scales with the account, never past the hard ceiling ────
# Sizing was a flat MAX_RISK_DOLLARS regardless of balance, so a growing account
# kept risking the same dollars and never compounded. Budget is now a percentage
# of live equity (bridge ACCOUNT_STATE.cash_value), which grows as the account
# grows and shrinks as it draws down.
#
# HARD_MAX_RISK_PCT is a ceiling on the CONFIG, not a target. Whatever
# RISK_PCT_OF_EQUITY is set to, per-trade risk can never exceed this share of the
# balance.
#
# The daily ceiling MUST scale too. It is checked pre-trade as
# realized_loss + full_trade_risk + costs > ceiling, so a fixed $1000 against a
# 3% ($1,511) trade risk would reject every trade forever and look like a broken
# bot rather than a risk limit. DAILY_LOSS_PCT_OF_EQUITY keeps the two in
# proportion; assess_trade reports incoherent settings explicitly.
#
# Equity unknown (bridge down, zero, or absent) falls back to the fixed dollar
# constants above — never to a larger number.
RISK_PCT_OF_EQUITY      = 1.00   # per-trade risk as % of equity
HARD_MAX_RISK_PCT       = 3.00   # absolute ceiling — config can never exceed this
DAILY_LOSS_PCT_OF_EQUITY = 2.00  # daily realized-loss ceiling as % of equity
COMPOUNDING_ENABLED     = True   # False restores flat MAX_RISK_DOLLARS sizing

MAX_SIMULTANEOUS_POSITIONS = 1
SCALE_IN = False
PYRAMIDING = False

# Preserve the existing primary decision window (America/New_York).
DECISION_WINDOW = ("09:30", "14:00")
TIMEZONE = "America/New_York"

# Modeled costs (honest placeholders; measured separately from Sim fills).
COMMISSION_PER_CONTRACT = None   # UNKNOWN -> labelled, not silently zero
SLIPPAGE_TICKS = 1.0

OPENAI_DISABLED = True
