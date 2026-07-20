# NinjaTrader MNQ Integration — Architecture

**Mission:** NINJATRADER-MNQ-INTEGRATION-FOUNDATION
**Decision:** `[NINJASCRIPT BRIDGE REQUIRED]` (see `data/integration/ninjatrader/architecture_decision.json`)

## Why a NinjaScript bridge

The organism needs completed 1-minute OHLCV bars, historical warm-up bars, real
volume, exact instrument metadata, and asynchronous account/order/execution/
position events. Evaluated options:

| Option | Verdict | Reason |
|---|---|---|
| **ATI managed DLL** (`NinjaTrader.Client.dll`, verified present, .NET Fx 4.8) | Rejected as primary | Poll-based; **no OHLCV bar events, no historical bars, no volume stream**. Would also need `pythonnet` (not installed; Python 3.14 wheel risk). |
| **ATI file interface** | Rejected | Fragile (race conditions, transient file deletion); no bars/volume/metadata. |
| **Native NinjaScript bridge** | **Selected** | One authoritative, event-driven surface for data **and** execution; pure-Python loopback socket client (no pythonnet); one reconciliation point; one forensic journal. |
| **Official Trader API** | Rejected | Entitlement-gated (NinjaTrader Brokerage); inappropriate for local Sim101; external dependency/cost. |

## Shape

```
  Python organism (frozen constitution)
    ├── market_data_provider.NinjaTraderMNQProvider  (BaseDataProvider)
    │       └── bar_gatekeeper.BarGatekeeper  (invariants + health states)
    ├── execution_adapter.NinjaTraderBrokerAdapter   (BrokerAdapter, DISARMED)
    │       └── account_safety  (Sim101-only, MNQ-only, qty<=1, fail-closed)
    └── bridge_client.NinjaTraderBridgeClient
                │  newline-delimited IPC envelopes (ipc_protocol)
                │  127.0.0.1:36901  (loopback ONLY)
                ▼
      MNQBridge.cs  (NinjaScript AddOn inside NinjaTrader 8)
                └── MasterInstrument metadata, Bars, Account/Order/Execution/Position
```

## Safety (defense in depth)

- **Account allowlist** = `{Sim101}` exactly, enforced in `account_safety` **and** in the
  NinjaScript bridge. Normalization only narrows, never broadens.
- **Instrument allowlist** = the exact resolved MNQ expiry; **NQ explicitly denied** at
  both the resolver and the bridge.
- **Quantity ceiling** = 1 whole contract; zero never rounds up.
- **Order submission DISARMED** (`AUTOMATED_ORDER_SUBMISSION_ARMED = False`) and no
  smoke-authorization token — `submit_order` denies before any wire call.
- **Uncertainty fails closed**: unknown connection / account-state / position-state /
  expiry all deny fresh entries. Managing an existing position is a separate path.
- **Loopback only**: the bridge binds `127.0.0.1`; the client refuses non-loopback hosts.

## IPC envelope

`protocol_version, message_type, message_id, correlation_id, sequence, sent_at,
instrument, expiry, account, payload, checksum`. Validation rejects version
mismatch, wrong account/instrument on commands, stale/future timestamps, malformed
JSON, and checksum mismatch; sequence gaps and out-of-order messages are surfaced;
duplicate command IDs are idempotent.

## Compiling the bridge (Maurice)

See `docs/integration/NINJATRADER_USER_SETUP.md` §F. The `.cs` is delivered as
source and compiled inside NT8. A few `NinjaTrader.Cbi` members may need a minor
adjustment for the exact NT8 build; compile errors, if any, will name the member.

## Known foundation limitations

- NT8 has never been launched here, so no live connection/metadata/bar proof exists yet.
- `BAR_CLOSED` / `QUOTE_UPDATE` / `POSITION_UPDATE` streaming in the bridge is stubbed
  pending a confirmed live data connection (read-only connection/metadata/account first).
- MNQ constants are asserted for internal consistency but **not yet reconciled** against
  MasterInstrument metadata (`metadata_verified = false`).
