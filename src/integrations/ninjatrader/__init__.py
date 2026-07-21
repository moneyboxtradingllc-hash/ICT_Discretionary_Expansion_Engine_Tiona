"""NINJATRADER-MNQ-INTEGRATION-FOUNDATION

Narrow provider/adapter boundary between the existing (frozen) Python trading
organism and NinjaTrader Desktop / DEMO8458533, for Micro E-mini Nasdaq-100 (MNQ)
simulation.

Constitution (frozen — NOT modified by this package):
  * The AI Brain is the sole author of fresh trade direction.
  * Trigger confirmation, narrative protected zones, and the Market Commander
    remain authoritative.
  * This package NEVER originates direction, never resizes beyond authorized
    quantity, and cannot route to a live account.

Safety posture of this package:
  * Account allowlist = {"DEMO8458533"} only; anything else fails CLOSED.
  * Instrument allowlist = the resolved exact active MNQ expiry only; NQ denied.
  * Maximum order quantity = 1 MNQ contract during the foundation era.
  * Automated order submission is DISARMED. No order is sent from Python in the
    foundation mission.
"""

INTEGRATION_ERA = "MNQ_NINJATRADER_FOUNDATION"
INTEGRATION_VERSION = "0.1.0-foundation"

# Foundation-era ceilings. These are floors of safety, not strategy knobs.
MAX_CONTRACTS_FOUNDATION = 1
AUTOMATED_ORDER_SUBMISSION_ARMED = False  # NEVER True in the foundation mission.
