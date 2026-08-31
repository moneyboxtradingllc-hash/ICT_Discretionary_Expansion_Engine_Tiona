"""TopstepX integration package.

LUNA-TOPSTEPX-ONLY (2026-08-31). TopstepX is the sole supported brokerage:
execution, market data and the deterministic lane.

`deterministic/` lived under `integrations/ninjatrader/` for historical
reasons -- the lane was written for a NinjaTrader bridge and later re-pointed at
TopstepX, but never moved. That namespace outlived its truth: the package
contained `topstepx_lane_client.py` and `topstepx_mutation_authority.py` while
claiming to be NinjaTrader. It has been extracted here, and the NinjaTrader
package was deleted outright rather than left as a forwarding alias -- a
compatibility namespace would keep exactly the ambiguity this move removes.
"""
