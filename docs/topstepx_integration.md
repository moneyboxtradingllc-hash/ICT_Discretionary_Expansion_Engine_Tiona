# TOPSTEPX-INTEGRATION — native venue path

*Mission opened 2026-08-04. Repo `ICT_Discretionary_Expansion_Engine`, branch
`ob-block-finder-and-evidence-diagnostics`. Phases 0–3 shipped; Phase 4 is
specification only and is NOT authorized to run.*

---

## Official documentation sources

Every endpoint, hub URL, subscription method and event name below was verified
against the official ProjectX Gateway API documentation on **2026-08-04**. None
was recalled from memory.

| Surface | Source |
|---|---|
| Connection URLs (API + both hubs) | `gateway.docs.projectx.com/docs/getting-started/connection-urls/` |
| API-key authentication | `gateway.docs.projectx.com/docs/getting-started/authenticate/authenticate-api-key/` |
| Account search + fields | `gateway.docs.projectx.com/docs/api-reference/account/search-accounts/` |
| Contract search + fields | `gateway.docs.projectx.com/docs/api-reference/market-data/search-contracts/` |
| Available contracts | `gateway.docs.projectx.com/docs/api-reference/market-data/available-contracts/` |
| Open-position search | `gateway.docs.projectx.com/docs/api-reference/positions/search-open-positions/` |
| Open-order search | `gateway.docs.projectx.com/docs/api-reference/order/order-search-open/` |
| Realtime hubs, methods, events | `gateway.docs.projectx.com/docs/realtime/` |

Verified constants:

- REST base `https://api.topstepx.com`
- User hub `https://rtc.topstepx.com/hubs/user`
- Market hub `https://rtc.topstepx.com/hubs/market`
- Account fields include `id`, `name`, `balance`, `canTrade`, **`isVisible`**
- Contract fields include `id`, `name`, `description`, `tickSize`, `tickValue`,
  `activeContract`, `symbolId`
- User hub: `SubscribeAccounts()`, `SubscribeOrders(accountId)`,
  `SubscribePositions(accountId)`, `SubscribeTrades(accountId)` →
  `GatewayUserAccount`, `GatewayUserOrder`, `GatewayUserPosition`, `GatewayUserTrade`
- Market hub: `SubscribeContractQuotes(contractId)`,
  `SubscribeContractTrades(contractId)` → `GatewayQuote`, `GatewayTrade`

---

## Phase 0 — venue inventory (what already existed)

| # | Concern | Where it lives |
|---|---|---|
| 1 | Venue abstraction | `src/broker/base.py` (`BrokerAdapter`, `BrokerCapability`, `NotConnectedError`); registry in `src/broker/factory.py` — default `paper` |
| 2 | NinjaTrader venue | `src/integrations/ninjatrader/` (`execution_adapter.py`, `bridge_client.py`, `deterministic/`) — **untouched by this mission** |
| 3 | Account selection | was `topstepx_client.account_by_name` — exact-name, fail-closed on 0 and >1 |
| 4 | Market data | `topstepx_client.bars()` → `/api/History/retrieveBars`; polling only |
| 5 | Order submission | `place_bracket_market_order` → `/api/Order/place` |
| 6 | Order state machine | `src/paper_execution/pending_order_lifecycle.py` |
| 7 | Fill normalization | `topstepx_adapter.submit_order` |
| 8 | Bracket / OCO | `src/paper_execution/bracket_builder.py`; venue-side attached stop/target in ticks |
| 9 | Position tracking | `open_positions()`; `position_monitor.py`, `position_supremacy.py` |
| 10 | Emergency flatten | `topstepx_adapter.flatten()` → `/api/Position/closeContract` |
| 11 | Startup preflight | `topstepx_preflight.py` (read-only by convention only) |
| 12 | Residual-order check | `open_orders()` |
| 13 | Risk seam | `src/risk/`, Topstep MLL sizing already wired |
| 14 | Execution seam | `src/execution_gate/execution_gate.py` |
| 15 | Secret convention | `.env` (gitignored) + `.env.template` (committed placeholders), `python-dotenv` |
| 16 | Existing TopstepX code | `topstepx_client.py`, `topstepx_adapter.py`, `topstepx_preflight.py`, `deterministic/topstepx_lane_client.py` |

### Gaps the inventory found

1. **No realtime at all.** Both hubs absent; `topstepx_client.py` said so in a comment.
2. **`isVisible` never read**, though it is a documented account field the pinning law requires.
3. **No account-identity-change detection** between runs.
4. **The preflight printed the TopstepX username in plaintext** — a credential, since it is half the `loginKey` payload.
5. **Read-only was a convention, not a structure** — the old preflight imported an adapter that owns `flatten()` and `submit_order()`.
6. **No 429 handling and no bounded backoff** — only a single 401 re-auth.

---

## Phase 1 — native adapter (shipped)

| File | Role |
|---|---|
| `src/broker/topstepx_redaction.py` | Total-mask redaction, JWT shape matching, account fingerprints, `assert_clean` write guard |
| `src/broker/topstepx_realtime.py` | Native SignalR JSON protocol on `websockets`; ordered subscription plan, deterministic replay, stale detection |
| `src/broker/topstepx_readonly.py` | Write-incapable session: no write methods + transport allowlist |
| `src/broker/topstepx_client.py` | +`pin_account`, +`available_contracts`, +`isVisible`, +429/backoff |

**No new dependency was added.** `signalrcore` is not installed; `websockets`
is. The SignalR JSON protocol these hubs need is a negotiate, a handshake frame
and record-separated JSON, so it is implemented natively — which is also what
"no runtime dependency on another bot" requires.

### Account-pinning law

`TopstepXClient.pin_account()` refuses, rather than choosing, when: nothing is
configured; zero accounts match; more than one matches; `canTrade` is false;
`isVisible` is false; or the resolved identity differs from a recorded
fingerprint. `TOPSTEPX_ACCOUNT_ID` is preferred over name — an integer id cannot
be made ambiguous by a rename. **List order is never a preference.**

### Contract discovery

`resolve_contract()` filters to `activeContract == true`, refuses ambiguity
(two active expiries mid-roll), and refuses non-positive `tickSize`/`tickValue`.
A stale hardcoded id is impossible: the id is only ever what the API returned.

---

## Phase 2 — read-only preflight (shipped)

```
python -m broker.topstepx_readonly_preflight
```

Read-only is **structural, in two independent layers**:

1. `TopstepXReadOnlySession` has no `place_order`, `submit_order`, `cancel_order`,
   `modify_order`, `close_position`, or `flatten`. `assert_no_write_surface()`
   proves the absence.
2. Every request passes an **allowlist** keyed on endpoint path. A write path
   raises `ReadOnlyViolation` before a byte leaves the process. The allowlist is
   positive, not a denylist — an endpoint TopstepX adds tomorrow is denied today.

Evidence lands at `data/integration/topstepx/readonly_preflight.json`,
repo-root-anchored, with UTC + Eastern timestamps, per-check state, redacted
account identity + fingerprint, contract metadata, both hubs' health,
subscription lists, reconnect result, market-data freshness, open position and
order counts, flat status, the zero-write proof and the redaction proof.

Freshness note: outside RTH a quiet market feed is expected, so staleness is a
**warning**, not a failure. A preflight that cannot be run in the evening is a
preflight that does not get run.

---

## Phase 3 — test locks (shipped)

`tests/test_topstepx_integration.py` — 62 locks, no network, no API subscription:

- **Authentication (7):** missing username/key, HTTP failure, `success: false`,
  empty token, absent API subscription named, one login reused
- **Rate limiting (4):** 429 retried within bound, retry limit enforced, backoff
  doubles without `Retry-After`, a refusal is never retried
- **Account pinning (9):** zero/multiple matches, exact match, first-account
  selection impossible, invisible, non-tradable, identity changed, identity
  stable, errors never print the account name
- **Contract discovery (5):** exact active resolve, inactive refused, roll
  ambiguity refused, invalid tick metadata refused, resolution follows the API
- **Realtime (11):** handshake, refused handshake, four user subscriptions, market
  subscriptions, duplicate prevention, ordered resubscription on reconnect, stale
  detection, malformed event survival, handler exception contained, keepalives not
  counted, health snapshot carries no token
- **Read-only enforcement (10):** no write methods exist, every known write path
  refused (parametrized), unknown endpoint denied by default, read path works,
  zero-write proof, real state read back
- **Redaction (9):** secrets masked, JWT by shape, bearer headers, secret-named
  keys, no partial-reveal mode, `assert_clean` is a real guard, fingerprint
  stability and non-reversibility
- **Preflight (6):** PASS verdict, zero-write artifact, no secret in the evidence
  file, both timestamps + stream health, unpinned account blocks pre-network,
  non-flat reported

---

## Phase 4 — execution smoke SPECIFICATION ONLY (**NOT AUTHORIZED**)

No execution smoke is authorized by this mission. This section is the
specification a future, separately authorized mission would implement.

**Venue:** a Topstep **Practice Account** first. The Combine account requires a
separate explicit operator authorization.

**Authorization:** the operator's exact phrase, plus a fresh one-use token
issued at preflight and **burned atomically at submit** — the same ritual the
NinjaTrader smoke used (`src/integrations/ninjatrader/smoke_order_path.py`).

Must prove, in order:

1. Exact pinned account (fingerprint matches the recorded preflight)
2. Exact active MNQ contract, resolved from the API in the same run
3. One MNQ market entry, size 1
4. Order acknowledgment with an order id
5. Fill confirmation **from the realtime `GatewayUserTrade` event**, not polling
6. Intended-versus-realized entry price and slippage
7. Signed stop-loss geometry — a long's stop is BELOW entry, a short's ABOVE,
   converted to ticks with `points_to_ticks` (rounds down, never wider)
8. Take-profit geometry on the correct side
9. Two protective orders confirmed **working** via `/api/Order/searchOpen`
10. OCO behavior: one protective side fills → the other is cancelled
11. Final position flat, verified by `/api/Position/searchOpen`
12. Zero residual working orders
13. Exact rejection reason on any refused route
14. A complete redacted evidence artifact

**Failure path:** emergency flatten via `/api/Position/closeContract`, then
residual-order sweep, then re-disarm. Incomplete fill-or-protection is treated
as the NinjaTrader lane treats it — flatten, do not hope.

---

## Standing boundaries honored

No prompt, strategy, entry, stop, sizing, risk-doctrine or management change.
No model calls, no API credit spend. The NinjaTrader venue is untouched. No
runtime dependency on any other repository. No secret material in source
control — `.env` stays gitignored and only placeholders are committed.
