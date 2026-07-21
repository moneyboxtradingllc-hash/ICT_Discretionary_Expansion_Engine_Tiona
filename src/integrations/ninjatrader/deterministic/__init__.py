"""DETERMINISTIC_MNQ_SIM_ONLY — a mechanical, sim-only automated trading lane.

Author is `deterministic_sim_author` (explicit predicates only). This lane NEVER
calls the AI Brain / OpenAI and never claims mechanical authorship is AI
authorship. Every opportunity it records is labelled mode+author.

Frozen doctrine (this lane):
  * Account : DEMO8458533 (sim only)     * Instrument : MNQ SEP26
  * Quantity: EXACTLY 5 contracts (5 or no trade — never auto-reduced)
  * Target  : fixed 35.00 points from the actual average fill
  * Stop    : the setup's STRUCTURAL invalidation; HARD cap 20.00 points
  * Max simultaneous positions: 1   * Max trades/day: 2
  * Daily realized-loss ceiling: $500 (gross-modeled pre-check)
  * Scale-in / pyramiding: FORBIDDEN
"""

MODE = "DETERMINISTIC_MNQ_SIM_ONLY"
AUTHOR = "deterministic_sim_author"
EVIDENCE_ERA = "MNQ_DETERMINISTIC_SIM_WEEK"

ACCOUNT = "DEMO8458533"
INSTRUMENT = "MNQ SEP26"

QUANTITY = 5                     # exactly five — never more, never fewer
POINT_VALUE = 2.00              # $ per index point per contract
DOLLARS_PER_POINT = POINT_VALUE * QUANTITY   # $10.00 per point at 5 contracts
TICK_SIZE = 0.25

TARGET_POINTS = 35.00           # fixed profit distance
MAX_STOP_POINTS = 20.00         # HARD structural-stop cap
MAX_GROSS_TRADE_RISK = MAX_STOP_POINTS * DOLLARS_PER_POINT   # $200
TARGET_GROSS_REWARD = TARGET_POINTS * DOLLARS_PER_POINT      # $350
MIN_RR_AT_MAX_STOP = TARGET_POINTS / MAX_STOP_POINTS         # 1.75

MAX_TRADES_PER_DAY = 2
DAILY_LOSS_CEILING = 500.00     # realized-loss ceiling ($)

MAX_SIMULTANEOUS_POSITIONS = 1
SCALE_IN = False
PYRAMIDING = False

# Preserve the existing primary decision window (America/New_York).
DECISION_WINDOW = ("09:30", "11:30")
TIMEZONE = "America/New_York"

# Modeled costs (honest placeholders; measured separately from Sim fills).
COMMISSION_PER_CONTRACT = None   # UNKNOWN -> labelled, not silently zero
SLIPPAGE_TICKS = 1.0

OPENAI_DISABLED = True
