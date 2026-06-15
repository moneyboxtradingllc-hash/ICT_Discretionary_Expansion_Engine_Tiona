# Tiona's Topstep Bot — Baby‑Step Setup Guide

Hi Tiona! This guide gets your trading bot connected to **your own Topstep
practice account**, one small step at a time. You don't need any coding
experience. Take it slowly — you can't break anything by following these steps.

**Important safety facts before we start:**
- This connects to your **practice / SIM 150K** account only — **not real money**.
- The bot will **not place any trades** until you deliberately turn execution on.
  We leave it **off** the whole way through this guide.
- These are **your** credentials. Maurice does **not** see them and should never
  ask for them. You type them into your own computer privately.
- Your login/password are **never** typed into the bot. The bot only uses an
  **API key** you generate (a long code), which you can delete anytime.

---

## Part A — Get your Topstep API key

### Step 1 — Log into TopstepX
1. Open your web browser.
2. Go to **https://www.topstepx.com** and sign in with your Topstep login.

### Step 2 — Find the API settings
1. Click the **gear / Settings (⚙️)** icon.
2. Click the **API** tab.

### Step 3 — Subscribe to API access (required, one time)
Topstep's API is provided through a partner called **ProjectX**, and it needs a
small subscription:
1. In the **API** tab, under **ProjectX Linking**, click **Link**.
2. Verify your email on the ProjectX page that opens.
3. Create a **ProjectX username and password** (write these down safely).
4. In your ProjectX dashboard, **subscribe to "ProjectX API Access."**
   - Cost: **$29/month**, and Topstep traders get 50% off with code **`topstep`**
     (= **$14.50/month**). This is separate from your normal Topstep fee.
   - *Tip:* you only need this active while you're running the bot.

### Step 4 — Create your API key
1. Go back to **TopstepX → Settings → API** tab.
2. Click **Add API Key**.
3. A long code appears. **This is your API key.**

### Step 5 — Copy the key safely
1. Click to **copy** the key.
2. Paste it somewhere private and temporary (a sticky note app is fine for a
   minute). **Do not** email it, post it, or send it to anyone — not even Maurice.
3. Also note your **ProjectX username** and your **account ID** (the practice
   150K account number, shown in TopstepX).

---

## Part B — Put the key into the bot

### Step 6 — Open the bot folder
On the bot computer, open this folder:
```
C:\Users\jesus\ICT_Discretionary_Expansion_Engine
```

### Step 7 — Open the `.env` file
1. In that folder, find the file named **`.env`** (just ".env", no name before
   the dot).
2. Open it with **Notepad** (right‑click → Open with → Notepad).
3. Scroll to the bottom — you'll see a block that starts with
   `# ── TIONA TOPSTEP (practice) ──`.

### Step 8 — Paste your API key
Find this line:
```
TOPSTEP_API_KEY=
```
Click right after the `=` and **paste your API key**. It becomes:
```
TOPSTEP_API_KEY=pjx_your_long_key_here
```
(No spaces, no quotes — just paste it right after the `=`.)

### Step 9 — Enter your username and account ID
Fill these two lines the same way:
```
TOPSTEP_USERNAME=your_projectx_username
TOPSTEP_ACCOUNT_ID=your_practice_account_number
```
Leave these two exactly as they are (they keep you safe):
```
TOPSTEP_ENV=practice
TOPSTEP_EXECUTION_ENABLED=false
```

### Step 10 — Save the file
Press **Ctrl + S** to save. Close Notepad. (Your key stays only on this computer;
the `.env` file is never uploaded or shared.)

---

## Part C — Test the connection (no trading)

### Step 11 — Run the connection test
1. Open **PowerShell** (Start menu → type "PowerShell" → Enter).
2. Type these two lines (press Enter after each):
```
cd C:\Users\jesus\ICT_Discretionary_Expansion_Engine
python tools/test_topstep_connection.py --instance tiona_topstep
```

### Step 12 — Confirm the bot sees your account
You should see something like:
```
✅ authenticated
=== ACCOUNT (read-only) ===
  account_id    : 1234567
  balance       : 150000
  can_trade     : True
  simulated     : True   (practice/sim)
  open positions: 0
  open orders   : 0
  health        : OK
✅ CONNECTION TEST PASSED
```
- `simulated: True` confirms it's your **practice** account (not real money).
- If you instead see *"Credentials not configured"*, go back to Steps 8–10.
- If you see *"authentication FAILED,"* double‑check the key/username and that
  your ProjectX API subscription is active, then re‑run.

### Step 13 — Confirm no orders are being placed
In that same output, look for:
```
order placement allowed now: False
this test placed NO orders and cancelled nothing.
```
`False` is correct and expected — trading is still **off**. Good.

---

## Part D — Start and stop the practice bot

### Step 14 — Start in practice mode (when you're ready)
First do a safe dry‑run (still places nothing):
```
python run_instance.py --instance tiona_topstep --dry-run
```
It should say memory/vector/journal are **empty** and **execution disabled** —
your bot is fresh and isolated.

When you actually want it scanning your practice account, the bot's separate
launch (with execution flags) is what turns trading on. **For now, keep
`TOPSTEP_EXECUTION_ENABLED=false`** — the bot will analyze but not place orders.
Ask Maurice before flipping execution on the first time.

### Step 15 — Stop the bot
In PowerShell, press **Ctrl + C** in the window where it's running. That stops
it immediately. (If it's running in the background, ask Maurice to stop the
process — there's a one‑line command for it.)

---

## Quick reference
| Action | Command |
|---|---|
| Test connection | `python tools/test_topstep_connection.py --instance tiona_topstep` |
| Dry‑run check | `python run_instance.py --instance tiona_topstep --dry-run` |
| Stop | `Ctrl + C` in the bot's window |

**Remember:** practice only, no real money, trades stay off until you choose to
enable them, and your API key is yours alone. You're in control. 🎯
