"""NEWS-1 — Market Intelligence Layer.

A market-AWARENESS layer (not a signal/trade/direction engine). It gives the AI
Brain awareness of information outside price action — scheduled economic
releases, breaking financial news, geopolitical shocks — as an additional
EVIDENCE source. The Brain decides what it means. News never generates trades,
never forces direction, never touches authority/execution/risk.

Gated by NEWS_LAYER_ENABLED (default false): when off the system is bit-for-bit
the pre-NEWS-1 pipeline. Offline + deterministic (local JSON sources) = safe for
paper trading.
"""
