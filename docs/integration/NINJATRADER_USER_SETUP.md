# NinjaTrader MNQ Simulation — User Setup Checklist

**Mission:** NINJATRADER-MNQ-INTEGRATION-FOUNDATION
**Account:** DEMO8458533 only · **Instrument:** Micro E-mini Nasdaq-100 (MNQ) · **Max:** 1 contract
**Automated order submission:** DISABLED (foundation). No order is sent by the bot.

> **Status (2026-07-21):** NinjaTrader 8 is **installed, launched, and running**;
> its user-data dir is `C:\Users\jesus\OneDrive\Documents\NinjaTrader 8` (OneDrive-
> redirected). Maurice is logged in. The account is **DEMO8458533**. The one
> remaining action for the live read-only path is **compiling the bridge (§F)** and
> confirming **Global Simulation Mode (§B)**. `MNQBridge.cs` has been deployed to the
> AddOns folder and **compiles cleanly against the NT8 assemblies** (static build) —
> it just needs to be compiled inside NT so it starts listening on `127.0.0.1:36901`.

---

## A. Install & log in

1. If NinjaTrader Desktop is not installed, download **NinjaTrader 8** from ninjatrader.com and install it.
2. Launch NinjaTrader 8 **at least once**. First launch creates the user-data tree
   (`Documents\NinjaTrader 8\...`) and the **DEMO8458533** account.
3. Log into the **free** NinjaTrader account when prompted (create one if needed).
4. In the **Control Center → Connections**, connect to the available
   **simulation / free market-data** connection (e.g. the built-in sim feed).

## B. Confirm the simulation account & safety

5. Open **Control Center → Accounts** and confirm **DEMO8458533** is listed.
6. Enable **Global Simulation Mode** (Control Center → right-click connection area / Tools).
   *(This is a NinjaTrader GUI safeguard. The bot's adapter ALSO enforces DEMO8458533
   independently — do not rely on this alone.)*
7. Confirm **no live/funded account** is connected or selected.

## C. Automated Trading Interface (ONLY if later required)

8. The selected architecture is a **NinjaScript bridge**, so the classic ATI is
   **NOT required** for the foundation. Skip ATI enablement for now.
   *(If a future mission selects the ATI DLL path: Tools → Options → Automated
   Trading Interface → enable, and set the default account to DEMO8458533.)*

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

## F. Compile the bridge (the one remaining action for the live path)

> `MNQBridge.cs` is **already deployed** to
> `C:\Users\jesus\OneDrive\Documents\NinjaTrader 8\bin\Custom\AddOns\MNQBridge.cs`
> and has been verified to compile cleanly against the NT8 assemblies. It only
> needs NinjaTrader to compile it so the AddOn instantiates and starts listening.

17. In NinjaTrader: **New → NinjaScript Editor**. Open any file, then press **F5**
    (Compile). This rebuilds `NinjaTrader.Custom.dll` including `MNQBridge`.
18. Confirm **no compile errors** in the Editor's error list. (The bridge binds
    **127.0.0.1 only**, account **hard-pinned to DEMO8458533**, **orders disarmed**.)
19. After a clean compile the AddOn starts automatically and listens on
    **127.0.0.1:36901**. Re-run `launch_ninjatrader_mnq_readonly.ps1` — it will now
    read connection/account/metadata/position live.
    *(If compile fails, send the exact error text; delete the `.cs` to fully revert.)*

---

## INFORMATION TO RETURN TO CLAUDE

Please send back only these facts (no passwords, no API keys, no account numbers):

- [ ] NinjaTrader **version** (Help → About)
- [ ] Exact **MNQ instrument display name** shown (e.g. `MNQ 09-26`)
- [ ] Exact **expiry** shown
- [ ] **Connection name** you connected to
- [ ] **DEMO8458533** visible in Accounts? (yes/no)
- [ ] Do **bid / ask / last** update on the MNQ chart? (yes/no)
- [ ] Does **volume** update? (yes/no)
- [ ] Do **historical bars** load on 1m/5m/15m? (yes/no)
- [ ] **Global Simulation Mode** enabled? (screenshot or text confirmation)
- [ ] Account selector showing **DEMO8458533** (screenshot or text confirmation)
- [ ] Did `MNQBridge.cs` **compile** cleanly? (yes/no + any error text)

Do **not** send passwords, API keys, brokerage credentials, or sensitive account info.
