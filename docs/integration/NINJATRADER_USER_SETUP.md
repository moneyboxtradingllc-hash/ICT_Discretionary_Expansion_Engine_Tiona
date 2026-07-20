# NinjaTrader MNQ Simulation — User Setup Checklist

**Mission:** NINJATRADER-MNQ-INTEGRATION-FOUNDATION
**Account:** Sim101 only · **Instrument:** Micro E-mini Nasdaq-100 (MNQ) · **Max:** 1 contract
**Automated order submission:** DISABLED (foundation). No order is sent by the bot.

> Preflight found NinjaTrader 8 **installed** at `C:\Program Files\NinjaTrader 8`
> but **never launched** (its `Documents\NinjaTrader 8` folder is empty). The steps
> below take it from "installed" to "read-only MNQ data path ready".

---

## A. Install & log in

1. If NinjaTrader Desktop is not installed, download **NinjaTrader 8** from ninjatrader.com and install it.
2. Launch NinjaTrader 8 **at least once**. First launch creates the user-data tree
   (`Documents\NinjaTrader 8\...`) and the **Sim101** account.
3. Log into the **free** NinjaTrader account when prompted (create one if needed).
4. In the **Control Center → Connections**, connect to the available
   **simulation / free market-data** connection (e.g. the built-in sim feed).

## B. Confirm the simulation account & safety

5. Open **Control Center → Accounts** and confirm **Sim101** is listed.
6. Enable **Global Simulation Mode** (Control Center → right-click connection area / Tools).
   *(This is a NinjaTrader GUI safeguard. The bot's adapter ALSO enforces Sim101
   independently — do not rely on this alone.)*
7. Confirm **no live/funded account** is connected or selected.

## C. Automated Trading Interface (ONLY if later required)

8. The selected architecture is a **NinjaScript bridge**, so the classic ATI is
   **NOT required** for the foundation. Skip ATI enablement for now.
   *(If a future mission selects the ATI DLL path: Tools → Options → Automated
   Trading Interface → enable, and set the default account to Sim101.)*

## D. Select the exact MNQ contract

9. In a chart or the instrument selector, search for **MNQ**.
10. Select the **exact current front-month expiry** (e.g. `MNQ 09-26`). **Do NOT**
    pick `NQ` (full size) or a continuous/merged `MNQ ##-##` symbol.
11. Open three charts on that exact expiry:
    - **1-minute**
    - **5-minute**
    - **15-minute**
12. Confirm the chart/instrument shows: **bid**, **ask**, **last**, **volume**,
    **timestamps**, and that **historical bars** load.
13. Confirm **no NQ chart or NQ account** is selected anywhere by accident.

## E. Save workspace & starting flat

14. Save a dedicated workspace named **`MNQ_BOT_SIM`** (File → Save Workspace As).
15. Confirm **no manual position is open** and **no working orders** exist before testing.
16. Locate in **Control Center**: **Accounts**, **Orders**, **Executions**,
    **Positions**, and the **Log** tab.

## F. Install the bridge (when ready to test the live data path)

17. Import `integrations/ninjatrader/ninjascript/MNQBridge.cs` into NinjaTrader:
    **New → NinjaScript Editor**, then right-click → **Import**, OR copy it into
    `Documents\NinjaTrader 8\bin\Custom\AddOns\` and press **F5** to compile.
18. Confirm it compiles with no errors. (The bridge binds **127.0.0.1 only** and
    has **orders disarmed**.)

---

## INFORMATION TO RETURN TO CLAUDE

Please send back only these facts (no passwords, no API keys, no account numbers):

- [ ] NinjaTrader **version** (Help → About)
- [ ] Exact **MNQ instrument display name** shown (e.g. `MNQ 09-26`)
- [ ] Exact **expiry** shown
- [ ] **Connection name** you connected to
- [ ] **Sim101** visible in Accounts? (yes/no)
- [ ] Do **bid / ask / last** update on the MNQ chart? (yes/no)
- [ ] Does **volume** update? (yes/no)
- [ ] Do **historical bars** load on 1m/5m/15m? (yes/no)
- [ ] **Global Simulation Mode** enabled? (screenshot or text confirmation)
- [ ] Account selector showing **Sim101** (screenshot or text confirmation)
- [ ] Did `MNQBridge.cs` **compile** cleanly? (yes/no + any error text)

Do **not** send passwords, API keys, brokerage credentials, or sensitive account info.
