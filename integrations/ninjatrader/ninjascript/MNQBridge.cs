// ======================================================================
// MNQBridge.cs
// NINJATRADER-MNQ-INTEGRATION-FOUNDATION — NinjaScript AddOn bridge
//
// SELECTED ARCHITECTURE: a single native NinjaScript AddOn running inside
// NinjaTrader 8 that exposes a LOOPBACK-ONLY TCP server (127.0.0.1) speaking
// the project IPC envelope to the Python organism. It is the one surface that
// can deliver completed 1-minute OHLCV bars, historical warm-up bars, real
// volume, exact MasterInstrument metadata, and account/order/execution/position
// events, without requiring pythonnet on the Python side.
//
// SAFETY (foundation era):
//   * Binds ONLY to 127.0.0.1. Never a routable interface.
//   * Account is HARD-PINNED to "DEMO8458533". Any other account is refused.
//   * Instrument is HARD-PINNED to the exact resolved MNQ expiry. NQ refused.
//   * ORDER SUBMISSION IS DISABLED in this foundation build (ArmOrders=false).
//     ORDER_SUBMIT_REQUEST is acknowledged with an ERROR("orders disarmed").
//
// DEPLOYMENT: import via NinjaTrader > New > NinjaScript Editor > (right-click)
// > Import, or copy to Documents\NinjaTrader 8\bin\Custom\AddOns\ and compile
// (F5). This file is delivered as SOURCE; it is compiled by Maurice inside NT8.
// Some API members may need a minor adjustment for the exact NT8 build — see
// docs/integration/NINJATRADER_ARCHITECTURE.md.
// ======================================================================
#region Using declarations
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
#endregion

namespace NinjaTrader.NinjaScript.AddOns
{
    public class MNQBridge : NinjaTrader.NinjaScript.AddOnBase
    {
        // ---- Foundation-era safety constants (defense in depth) ----
        private const string PROTOCOL_VERSION = "1.0.0";
        private const string ALLOWED_ACCOUNT = "DEMO8458533";
        private const string ALLOWED_INSTRUMENT = "MNQ SEP26";  // exact pinned expiry
        private const int    MAX_CONTRACTS   = 1;
        private const double STOP_POINTS     = 5.0;   // smoke-test protective stop distance
        private const double TARGET_POINTS   = 5.0;   // smoke-test profit target distance
        // Deterministic lane doctrine.
        private const int    DET_QTY         = 5;     // exactly five
        private const double DET_TARGET_PTS  = 35.0;  // fixed target
        private const double DET_MAX_STOP    = 20.0;  // hard structural-stop cap
        private const bool   ArmOrders       = false; // physical disarm — flip ONLY at the authorized SEND step.
        private const string LoopbackAddress = "127.0.0.1";
        private const int    ListenPort      = 36901;   // loopback only

        private TcpListener  listener;
        private Thread       acceptThread;
        private volatile bool running;
        private long         sequence;
        private readonly object writeLock = new object();

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name        = "MNQBridge";
                Description = "Loopback IPC bridge to the Python organism (DEMO8458533/MNQ, orders DISARMED).";
            }
            else if (State == State.Configure)
            {
                StartServer();
            }
            else if (State == State.Terminated)
            {
                StopServer();
            }
        }

        private void StartServer()
        {
            if (running) return;
            running = true;
            // Bind LOOPBACK ONLY — never IPAddress.Any.
            listener = new TcpListener(IPAddress.Parse(LoopbackAddress), ListenPort);
            listener.Start();
            acceptThread = new Thread(AcceptLoop) { IsBackground = true, Name = "MNQBridgeAccept" };
            acceptThread.Start();
        }

        private void StopServer()
        {
            running = false;
            try { if (listener != null) listener.Stop(); } catch { }
        }

        private void AcceptLoop()
        {
            while (running)
            {
                try
                {
                    var client = listener.AcceptTcpClient();
                    var t = new Thread(() => Serve(client)) { IsBackground = true };
                    t.Start();
                }
                catch { if (running) Thread.Sleep(200); }
            }
        }

        private void Serve(TcpClient client)
        {
            using (client)
            using (var stream = client.GetStream())
            {
                SendEnvelope(stream, "HELLO_ACK", "{\"role\":\"bridge\"}", "", "", "");
                var buf = new byte[8192];
                var sb = new StringBuilder();
                while (running && client.Connected)
                {
                    int n;
                    try { n = stream.Read(buf, 0, buf.Length); }
                    catch { break; }
                    if (n <= 0) break;
                    sb.Append(Encoding.UTF8.GetString(buf, 0, n));
                    string all = sb.ToString();
                    int nl;
                    while ((nl = all.IndexOf('\n')) >= 0)
                    {
                        string line = all.Substring(0, nl);
                        all = all.Substring(nl + 1);
                        HandleLine(stream, line);
                    }
                    sb.Clear();
                    sb.Append(all);
                }
            }
        }

        // Extremely small hand-parser: we only need message_type + account +
        // instrument for the foundation. A full JSON parser is added when the
        // order path is armed in a later mission.
        private void HandleLine(NetworkStream stream, string line)
        {
            string mtype = ExtractJsonString(line, "message_type");
            string account = ExtractJsonString(line, "account");
            string instrument = ExtractJsonString(line, "instrument");

            switch (mtype)
            {
                case "HELLO":
                    SendConnectionState(stream);
                    break;
                case "INSTRUMENT_METADATA":
                    SendInstrumentMetadata(stream, instrument);
                    break;
                case "ACCOUNT_STATE":
                    SendAccountState(stream, account);
                    break;
                case "ENVIRONMENT_PROOF":
                    SendEnvironmentProof(stream);
                    break;
                case "POSITION_UPDATE":
                    SendPosition(stream, account, instrument);
                    break;
                case "ORDER_UPDATE":
                    SendWorkingOrders(stream, account);
                    break;
                case "QUOTE_UPDATE":
                    SendQuote(stream, instrument);
                    break;
                case "HISTORICAL_BARS_REQUEST":
                    SendHistoricalBars(stream, instrument);
                    break;
                case "ORDER_SUBMIT_REQUEST":
                case "ORDER_CANCEL_REQUEST":
                    // DEFENSE IN DEPTH: physical disarm (ArmOrders const false) +
                    // account/instrument/qty/direction pinning. While disarmed the
                    // bridge REFUSES every order request; the armed branch (which
                    // becomes reachable only when ArmOrders is deliberately flipped
                    // and NT recompiled) is where SubmitSmokeBracket runs.
#pragma warning disable 162
                    if (!ArmOrders)
                        SendEnvelope(stream, "ERROR", "{\"reason\":\"orders disarmed (ArmOrders=false)\"}", account, instrument, "");
                    else if (mtype == "ORDER_CANCEL_REQUEST")
                        FlattenAllowed(stream, account, instrument);
                    else if (account != ALLOWED_ACCOUNT)
                        SendEnvelope(stream, "ERROR", "{\"reason\":\"account not allowlisted\"}", account, instrument, "");
                    else if (instrument != ALLOWED_INSTRUMENT)
                        SendEnvelope(stream, "ERROR", "{\"reason\":\"instrument not the pinned MNQ expiry\"}", account, instrument, "");
                    else
                        SubmitSmokeBracket(stream, account, instrument, line);
#pragma warning restore 162
                    break;
                case "DETERMINISTIC_ORDER":
#pragma warning disable 162
                    if (!ArmOrders)
                        SendEnvelope(stream, "ERROR", "{\"reason\":\"orders disarmed (ArmOrders=false)\"}", account, instrument, "");
                    else if (account != ALLOWED_ACCOUNT)
                        SendEnvelope(stream, "ERROR", "{\"reason\":\"account not allowlisted\"}", account, instrument, "");
                    else if (instrument != ALLOWED_INSTRUMENT)
                        SendEnvelope(stream, "ERROR", "{\"reason\":\"instrument not the pinned MNQ expiry\"}", account, instrument, "");
                    else
                        SubmitDeterministicBracket(stream, account, instrument, line);
#pragma warning restore 162
                    break;
                case "HEARTBEAT":
                    SendEnvelope(stream, "HEARTBEAT", "{}", account, instrument, "");
                    break;
                default:
                    SendEnvelope(stream, "ERROR", "{\"reason\":\"unknown message_type\"}", account, instrument, "");
                    break;
            }
        }

        private void SendConnectionState(NetworkStream stream)
        {
            bool connected = false;
            try
            {
                foreach (Connection c in Connection.Connections)
                { if (c.Status == ConnectionStatus.Connected) { connected = true; break; } }
            }
            catch { }
            string payload = "{\"connected\":" + (connected ? "true" : "false") + "}";
            SendEnvelope(stream, "CONNECTION_STATE", payload, "", "", "");
        }

        private void SendInstrumentMetadata(NetworkStream stream, string instrumentName)
        {
            try
            {
                Instrument instr = Instrument.GetInstrument(instrumentName);
                if (instr == null || instr.MasterInstrument == null)
                {
                    SendEnvelope(stream, "ERROR", "{\"reason\":\"instrument not found\"}", "", instrumentName, "");
                    return;
                }
                // Refuse full-size NQ masquerading.
                string root = instr.MasterInstrument.Name;
                if (root == "NQ")
                {
                    SendEnvelope(stream, "ERROR", "{\"reason\":\"NQ denied\"}", "", instrumentName, "");
                    return;
                }
                double tick  = instr.MasterInstrument.TickSize;
                double pv     = instr.MasterInstrument.PointValue;
                string payload = string.Format(CultureInfo.InvariantCulture,
                    "{{\"instrument_name\":\"{0}\",\"root\":\"{1}\",\"tick_size\":{2},\"point_value\":{3},\"currency\":\"{4}\"}}",
                    instr.FullName, root, tick, pv, instr.MasterInstrument.Currency);
                SendEnvelope(stream, "INSTRUMENT_METADATA", payload, "", instr.FullName, "");
            }
            catch (Exception ex)
            {
                SendEnvelope(stream, "ERROR", "{\"reason\":\"" + Escape(ex.Message) + "\"}", "", instrumentName, "");
            }
        }

        private void SendAccountState(NetworkStream stream, string accountName)
        {
            // Foundation: only ever report the DEMO8458533 account.
            if (accountName != ALLOWED_ACCOUNT)
            {
                SendEnvelope(stream, "ERROR", "{\"reason\":\"account not allowlisted\"}", accountName, "", "");
                return;
            }
            try
            {
                Account acct = null;
                foreach (Account a in Account.All)
                { if (a.Name == ALLOWED_ACCOUNT) { acct = a; break; } }
                if (acct == null)
                {
                    SendEnvelope(stream, "ERROR", "{\"reason\":\"DEMO8458533 not found\"}", accountName, "", "");
                    return;
                }
                double cash = acct.Get(AccountItem.CashValue, Currency.UsDollar);
                string payload = string.Format(CultureInfo.InvariantCulture,
                    "{{\"account\":\"{0}\",\"cash_value\":{1}}}", ALLOWED_ACCOUNT, cash);
                SendEnvelope(stream, "ACCOUNT_STATE", payload, ALLOWED_ACCOUNT, "", "");
            }
            catch (Exception ex)
            {
                SendEnvelope(stream, "ERROR", "{\"reason\":\"" + Escape(ex.Message) + "\"}", accountName, "", "");
            }
        }

        private Account FindAllowedAccount()
        {
            foreach (Account a in Account.All)
                if (a.Name == ALLOWED_ACCOUNT) return a;
            return null;
        }

        // Read-only proof of the connected environment: every account with its
        // provider + connection status, so the Python side can positively prove
        // it is the Simulation environment and that no live account is present.
        private void SendEnvironmentProof(NetworkStream stream)
        {
            try
            {
                var accs = new StringBuilder();
                foreach (Account a in Account.All)
                {
                    string prov = "";
                    string connName = "";
                    string connStatus = "None";
                    try { prov = a.Provider.ToString(); } catch { }
                    try {
                        if (a.Connection != null)
                        {
                            connStatus = a.Connection.Status.ToString();
                            if (a.Connection.Options != null) connName = a.Connection.Options.Name;
                        }
                    } catch { }
                    if (accs.Length > 0) accs.Append(",");
                    accs.AppendFormat(CultureInfo.InvariantCulture,
                        "{{\"name\":\"{0}\",\"provider\":\"{1}\",\"connection\":\"{2}\",\"status\":\"{3}\"}}",
                        Escape(a.Name), Escape(prov), Escape(connName), Escape(connStatus));
                }
                var conns = new StringBuilder();
                try
                {
                    foreach (Connection c in Connection.Connections)
                    {
                        string nm = "";
                        try { if (c.Options != null) nm = c.Options.Name; } catch { }
                        if (conns.Length > 0) conns.Append(",");
                        conns.AppendFormat(CultureInfo.InvariantCulture,
                            "{{\"name\":\"{0}\",\"status\":\"{1}\"}}", Escape(nm), c.Status.ToString());
                    }
                }
                catch { }
                string payload = string.Format(CultureInfo.InvariantCulture,
                    "{{\"allowed_account\":\"{0}\",\"arm_orders\":{1},\"accounts\":[{2}],\"connections\":[{3}]}}",
                    ALLOWED_ACCOUNT, ArmOrders ? "true" : "false", accs.ToString(), conns.ToString());
                SendEnvelope(stream, "ENVIRONMENT_PROOF", payload, ALLOWED_ACCOUNT, "", "");
            }
            catch (Exception ex)
            {
                SendEnvelope(stream, "ERROR", "{\"reason\":\"" + Escape(ex.Message) + "\"}", "", "", "");
            }
        }

        // Read-only net position for the exact instrument. Flat -> qty 0.
        private void SendPosition(NetworkStream stream, string accountName, string instrumentName)
        {
            if (accountName != ALLOWED_ACCOUNT)
            {
                SendEnvelope(stream, "ERROR", "{\"reason\":\"account not allowlisted\"}", accountName, instrumentName, "");
                return;
            }
            try
            {
                Account acct = FindAllowedAccount();
                if (acct == null)
                {
                    SendEnvelope(stream, "ERROR", "{\"reason\":\"DEMO8458533 not found\"}", accountName, instrumentName, "");
                    return;
                }
                int qty = 0;
                string mp = "Flat";
                double avg = 0;
                foreach (Position p in acct.Positions)
                {
                    if (p.Instrument != null && p.Instrument.FullName == instrumentName)
                    {
                        mp = p.MarketPosition.ToString();
                        int q = p.Quantity;
                        qty = (p.MarketPosition == MarketPosition.Short) ? -q : q;
                        avg = p.AveragePrice;
                        break;
                    }
                }
                bool flat = (qty == 0);
                string payload = string.Format(CultureInfo.InvariantCulture,
                    "{{\"instrument\":\"{0}\",\"qty\":{1},\"market_position\":\"{2}\",\"avg_price\":{3},\"flat\":{4},\"known\":true}}",
                    Escape(instrumentName), qty, mp, avg, flat ? "true" : "false");
                SendEnvelope(stream, "POSITION_UPDATE", payload, ALLOWED_ACCOUNT, instrumentName, "");
            }
            catch (Exception ex)
            {
                SendEnvelope(stream, "ERROR", "{\"reason\":\"" + Escape(ex.Message) + "\"}", accountName, instrumentName, "");
            }
        }

        // Read-only count of live/working orders on the account.
        private void SendWorkingOrders(NetworkStream stream, string accountName)
        {
            if (accountName != ALLOWED_ACCOUNT)
            {
                SendEnvelope(stream, "ERROR", "{\"reason\":\"account not allowlisted\"}", accountName, "", "");
                return;
            }
            try
            {
                Account acct = FindAllowedAccount();
                if (acct == null)
                {
                    SendEnvelope(stream, "ERROR", "{\"reason\":\"DEMO8458533 not found\"}", accountName, "", "");
                    return;
                }
                int working = 0;
                foreach (Order o in acct.Orders)
                {
                    switch (o.OrderState)
                    {
                        case OrderState.Working:
                        case OrderState.Accepted:
                        case OrderState.Submitted:
                        case OrderState.TriggerPending:
                        case OrderState.PartFilled:
                        case OrderState.ChangePending:
                        case OrderState.CancelPending:
                            working++;
                            break;
                    }
                }
                string payload = string.Format(CultureInfo.InvariantCulture,
                    "{{\"working_order_count\":{0},\"orders\":[],\"known\":true}}", working);
                SendEnvelope(stream, "ORDER_UPDATE", payload, ALLOWED_ACCOUNT, "", "");
            }
            catch (Exception ex)
            {
                SendEnvelope(stream, "ERROR", "{\"reason\":\"" + Escape(ex.Message) + "\"}", accountName, "", "");
            }
        }

        // Read-only snapshot of last/bid/ask/volume from the cached L1 data (needs
        // an active subscription, e.g. an open MNQ chart). Nulls -> reported absent.
        private void SendQuote(NetworkStream stream, string instrumentName)
        {
            try
            {
                Instrument instr = Instrument.GetInstrument(instrumentName);
                if (instr == null)
                {
                    SendEnvelope(stream, "ERROR", "{\"reason\":\"instrument not found\"}", "", instrumentName, "");
                    return;
                }
                double last = 0, bid = 0, ask = 0, vol = 0;
                bool haveLast = false, haveBid = false, haveAsk = false;
                try {
                    var md = instr.MarketData;
                    if (md != null)
                    {
                        if (md.Last != null) { last = md.Last.Price; vol = md.Last.Volume; haveLast = true; }
                        if (md.Bid  != null) { bid  = md.Bid.Price;  haveBid = true; }
                        if (md.Ask  != null) { ask  = md.Ask.Price;  haveAsk = true; }
                    }
                } catch { }
                string payload = string.Format(CultureInfo.InvariantCulture,
                    "{{\"instrument\":\"{0}\",\"last\":{1},\"bid\":{2},\"ask\":{3},\"volume\":{4},\"have_last\":{5},\"have_bid\":{6},\"have_ask\":{7}}}",
                    Escape(instr.FullName), last, bid, ask, vol,
                    haveLast ? "true" : "false", haveBid ? "true" : "false", haveAsk ? "true" : "false");
                SendEnvelope(stream, "QUOTE_UPDATE", payload, "", instr.FullName, "");
            }
            catch (Exception ex)
            {
                SendEnvelope(stream, "ERROR", "{\"reason\":\"" + Escape(ex.Message) + "\"}", "", instrumentName, "");
            }
        }

        // Read-only historical 1-minute bars (last ~1 day). Blocks up to a few
        // seconds for the async BarsRequest callback.
        private void SendHistoricalBars(NetworkStream stream, string instrumentName)
        {
            try
            {
                Instrument instr = Instrument.GetInstrument(instrumentName);
                if (instr == null)
                {
                    SendEnvelope(stream, "ERROR", "{\"reason\":\"instrument not found\"}", "", instrumentName, "");
                    return;
                }
                var done = new System.Threading.ManualResetEventSlim(false);
                var sb = new StringBuilder();
                int[] count = { 0 };
                string[] err = { null };
                DateTime to = DateTime.Now;
                DateTime from = to.AddDays(-5);   // enough history for structural analysis
                BarsRequest req = new BarsRequest(instr, from, to);
                req.BarsPeriod = new BarsPeriod { BarsPeriodType = BarsPeriodType.Minute, Value = 1 };
                req.Request((request, errorCode, errorMessage) =>
                {
                    try
                    {
                        if (errorCode != ErrorCode.NoError)
                        {
                            err[0] = errorCode.ToString() + ":" + errorMessage;
                        }
                        else if (request != null && request.Bars != null)
                        {
                            int n = request.Bars.Count;
                            int start = Math.Max(0, n - 400);  // deep history for structure engines
                            for (int i = start; i < n; i++)
                            {
                                if (sb.Length > 0) sb.Append(",");
                                // Stamp with the machine-local offset so the time is
                                // timezone-AWARE downstream (NT bar times are local).
                                DateTime bt = DateTime.SpecifyKind(request.Bars.GetTime(i), DateTimeKind.Local);
                                sb.AppendFormat(CultureInfo.InvariantCulture,
                                    "{{\"t\":\"{0:o}\",\"o\":{1},\"h\":{2},\"l\":{3},\"c\":{4},\"v\":{5}}}",
                                    bt, request.Bars.GetOpen(i),
                                    request.Bars.GetHigh(i), request.Bars.GetLow(i),
                                    request.Bars.GetClose(i), request.Bars.GetVolume(i));
                            }
                            count[0] = n;
                        }
                    }
                    catch (Exception e2) { err[0] = e2.Message; }
                    finally { done.Set(); }
                });
                done.Wait(5000);
                try { req.Dispose(); } catch { }
                if (err[0] != null)
                {
                    SendEnvelope(stream, "ERROR", "{\"reason\":\"" + Escape(err[0]) + "\"}", "", instr.FullName, "");
                    return;
                }
                string payload = string.Format(CultureInfo.InvariantCulture,
                    "{{\"instrument\":\"{0}\",\"total_bars\":{1},\"bars\":[{2}]}}",
                    Escape(instr.FullName), count[0], sb.ToString());
                SendEnvelope(stream, "HISTORICAL_BARS_RESPONSE", payload, "", instr.FullName, "");
            }
            catch (Exception ex)
            {
                SendEnvelope(stream, "ERROR", "{\"reason\":\"" + Escape(ex.Message) + "\"}", "", instrumentName, "");
            }
        }

        // ARMED order path — reachable ONLY when ArmOrders is deliberately flipped
        // true and NinjaTrader is recompiled. Submits exactly one LONG MARKET
        // contract on DEMO8458533 and, on fill, attaches an OCO stop (5 pts below)
        // and target (5 pts above); if protection cannot be established it flattens.
        private void SubmitSmokeBracket(NetworkStream stream, string accountName, string instrumentName, string line)
        {
            try
            {
                string dir = ExtractJsonString(line, "direction").ToLower();
                int qty = (int)ExtractJsonNumber(line, "quantity");
                if (dir != "long" && dir != "buy")
                { SendEnvelope(stream, "ERROR", "{\"reason\":\"direction not LONG\"}", accountName, instrumentName, ""); return; }
                if (qty != MAX_CONTRACTS)
                { SendEnvelope(stream, "ERROR", "{\"reason\":\"quantity must be exactly 1\"}", accountName, instrumentName, ""); return; }

                Account acct = FindAllowedAccount();
                Instrument instr = Instrument.GetInstrument(instrumentName);
                if (acct == null || instr == null || instr.MasterInstrument == null)
                { SendEnvelope(stream, "ERROR", "{\"reason\":\"account or instrument missing\"}", accountName, instrumentName, ""); return; }
                if (instr.MasterInstrument.Name == "NQ")
                { SendEnvelope(stream, "ERROR", "{\"reason\":\"NQ denied\"}", accountName, instrumentName, ""); return; }

                string oco = "SMOKE-OCO-" + Guid.NewGuid().ToString("N");
                EventHandler<ExecutionEventArgs> execHandler = null;
                execHandler = (object s, ExecutionEventArgs e) =>
                {
                    try
                    {
                        if (e.Execution == null || e.Execution.Order == null) return;
                        if (e.Execution.Order.Name != "SmokeEntry") return;
                        if (e.Execution.Order.OrderState != OrderState.Filled) return;
                        double fill = e.Execution.Order.AverageFillPrice;
                        double stopPrice = instr.MasterInstrument.RoundToTickSize(fill - STOP_POINTS);
                        double tgtPrice = instr.MasterInstrument.RoundToTickSize(fill + TARGET_POINTS);
                        Order stop = acct.CreateOrder(instr, OrderAction.Sell, OrderType.StopMarket, OrderEntry.Manual, TimeInForce.Day, MAX_CONTRACTS, 0, stopPrice, oco, "SmokeStop", NinjaTrader.Core.Globals.MaxDate, null);
                        Order tgt = acct.CreateOrder(instr, OrderAction.Sell, OrderType.Limit, OrderEntry.Manual, TimeInForce.Day, MAX_CONTRACTS, tgtPrice, 0, oco, "SmokeTarget", NinjaTrader.Core.Globals.MaxDate, null);
                        // This handler runs ASYNC (after the request socket may be
                        // closed); it must NOT write to the socket. It attaches OCO
                        // silently; on failure it flattens. Python verifies by polling
                        // position + working orders.
                        try
                        {
                            acct.Submit(new[] { stop, tgt });
                        }
                        catch
                        {
                            try { acct.Flatten(new[] { instr }); } catch { }   // EMERGENCY FLATTEN
                        }
                        acct.ExecutionUpdate -= execHandler;
                    }
                    catch { }
                };
                acct.ExecutionUpdate += execHandler;

                Order entry = acct.CreateOrder(instr, OrderAction.Buy, OrderType.Market, OrderEntry.Manual, TimeInForce.Day, MAX_CONTRACTS, 0, 0, "", "SmokeEntry", NinjaTrader.Core.Globals.MaxDate, null);
                acct.Submit(new[] { entry });
                SendEnvelope(stream, "ORDER_ACK", "{\"accepted\":true,\"entry\":\"submitted\"}", accountName, instrumentName, "");
            }
            catch (Exception ex)
            {
                SendEnvelope(stream, "ERROR", "{\"reason\":\"" + Escape(ex.Message) + "\"}", accountName, instrumentName, "");
            }
        }

        // DETERMINISTIC lane bracket: exactly 5 contracts, LONG or SHORT, a
        // STRUCTURAL stop price supplied by the strategy, and a fixed 35-pt target
        // from the actual fill. On fill it re-checks the true stop distance vs the
        // 20-pt cap and EMERGENCY-FLATTENS if slippage breached it.
        private void SubmitDeterministicBracket(NetworkStream stream, string accountName, string instrumentName, string line)
        {
            try
            {
                string dir = ExtractJsonString(line, "direction").ToLower();
                int qty = (int)ExtractJsonNumber(line, "quantity");
                double structuralStop = ExtractJsonNumber(line, "structural_stop_price");
                if (dir != "long" && dir != "short")
                { SendEnvelope(stream, "ERROR", "{\"reason\":\"direction must be long or short\"}", accountName, instrumentName, ""); return; }
                if (qty != DET_QTY)
                { SendEnvelope(stream, "ERROR", "{\"reason\":\"quantity must be exactly 5\"}", accountName, instrumentName, ""); return; }
                if (structuralStop <= 0)
                { SendEnvelope(stream, "ERROR", "{\"reason\":\"structural stop price required\"}", accountName, instrumentName, ""); return; }

                Account acct = FindAllowedAccount();
                Instrument instr = Instrument.GetInstrument(instrumentName);
                if (acct == null || instr == null || instr.MasterInstrument == null)
                { SendEnvelope(stream, "ERROR", "{\"reason\":\"account or instrument missing\"}", accountName, instrumentName, ""); return; }
                if (instr.MasterInstrument.Name == "NQ")
                { SendEnvelope(stream, "ERROR", "{\"reason\":\"NQ denied\"}", accountName, instrumentName, ""); return; }

                bool isLong = (dir == "long");
                OrderAction entryAction = isLong ? OrderAction.Buy : OrderAction.SellShort;
                OrderAction exitAction = isLong ? OrderAction.Sell : OrderAction.BuyToCover;
                double stopPx = instr.MasterInstrument.RoundToTickSize(structuralStop);
                string oco = "DET-OCO-" + Guid.NewGuid().ToString("N");

                EventHandler<ExecutionEventArgs> execHandler = null;
                execHandler = (object s, ExecutionEventArgs e) =>
                {
                    try
                    {
                        if (e.Execution == null || e.Execution.Order == null) return;
                        if (e.Execution.Order.Name != "DetEntry") return;
                        if (e.Execution.Order.OrderState != OrderState.Filled) return;
                        double fill = e.Execution.Order.AverageFillPrice;
                        // Fill-slippage re-check against the 20-pt cap.
                        double actualStopDist = Math.Abs(fill - stopPx);
                        if (actualStopDist > DET_MAX_STOP + 1e-9)
                        {
                            try { acct.Flatten(new[] { instr }); } catch { }   // EMERGENCY FLATTEN
                            acct.ExecutionUpdate -= execHandler;
                            return;
                        }
                        double tgtPx = isLong
                            ? instr.MasterInstrument.RoundToTickSize(fill + DET_TARGET_PTS)
                            : instr.MasterInstrument.RoundToTickSize(fill - DET_TARGET_PTS);
                        Order stop = acct.CreateOrder(instr, exitAction, OrderType.StopMarket, OrderEntry.Manual, TimeInForce.Day, DET_QTY, 0, stopPx, oco, "DetStop", NinjaTrader.Core.Globals.MaxDate, null);
                        Order tgt = acct.CreateOrder(instr, exitAction, OrderType.Limit, OrderEntry.Manual, TimeInForce.Day, DET_QTY, tgtPx, 0, oco, "DetTarget", NinjaTrader.Core.Globals.MaxDate, null);
                        try { acct.Submit(new[] { stop, tgt }); }
                        catch { try { acct.Flatten(new[] { instr }); } catch { } }
                        acct.ExecutionUpdate -= execHandler;
                    }
                    catch { }
                };
                acct.ExecutionUpdate += execHandler;

                Order entry = acct.CreateOrder(instr, entryAction, OrderType.Market, OrderEntry.Manual, TimeInForce.Day, DET_QTY, 0, 0, "", "DetEntry", NinjaTrader.Core.Globals.MaxDate, null);
                acct.Submit(new[] { entry });
                SendEnvelope(stream, "ORDER_ACK", "{\"accepted\":true,\"entry\":\"submitted\",\"lane\":\"deterministic\"}", accountName, instrumentName, "");
            }
            catch (Exception ex)
            {
                SendEnvelope(stream, "ERROR", "{\"reason\":\"" + Escape(ex.Message) + "\"}", accountName, instrumentName, "");
            }
        }

        private void FlattenAllowed(NetworkStream stream, string accountName, string instrumentName)
        {
            try
            {
                Account acct = FindAllowedAccount();
                Instrument instr = Instrument.GetInstrument(instrumentName);
                if (acct == null || instr == null)
                { SendEnvelope(stream, "ERROR", "{\"reason\":\"account or instrument missing\"}", accountName, instrumentName, ""); return; }
                // Cancel any working orders on this instrument, then flatten.
                var toCancel = new List<Order>();
                foreach (Order o in acct.Orders)
                    if (o.Instrument != null && o.Instrument.FullName == instr.FullName) toCancel.Add(o);
                if (toCancel.Count > 0) { try { acct.Cancel(toCancel); } catch { } }
                acct.Flatten(new[] { instr });
                SendEnvelope(stream, "ORDER_UPDATE", "{\"ok\":true,\"flattened\":true}", accountName, instrumentName, "");
            }
            catch (Exception ex)
            {
                SendEnvelope(stream, "ERROR", "{\"reason\":\"" + Escape(ex.Message) + "\"}", accountName, instrumentName, "");
            }
        }

        private void SendEnvelope(NetworkStream stream, string type, string payloadJson,
                                  string account, string instrument, string expiry)
        {
            long seq = Interlocked.Increment(ref sequence);
            double sentAt = (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
            string env = string.Format(CultureInfo.InvariantCulture,
                "{{\"protocol_version\":\"{0}\",\"message_type\":\"{1}\",\"message_id\":\"{2}\"," +
                "\"correlation_id\":\"\",\"sequence\":{3},\"sent_at\":{4}," +
                "\"instrument\":\"{5}\",\"expiry\":\"{6}\",\"account\":\"{7}\",\"payload\":{8}}}\n",
                PROTOCOL_VERSION, type, Guid.NewGuid().ToString("N"), seq,
                sentAt.ToString(CultureInfo.InvariantCulture), Escape(instrument),
                Escape(expiry), Escape(account), payloadJson);
            byte[] bytes = Encoding.UTF8.GetBytes(env);
            lock (writeLock)
            {
                try { stream.Write(bytes, 0, bytes.Length); stream.Flush(); } catch { }
            }
        }

        private static string Escape(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return s.Replace("\\", "\\\\").Replace("\"", "\\\"");
        }

        private static double ExtractJsonNumber(string json, string key)
        {
            string needle = "\"" + key + "\"";
            int i = json.IndexOf(needle, StringComparison.Ordinal);
            if (i < 0) return 0;
            i = json.IndexOf(':', i + needle.Length);
            if (i < 0) return 0;
            int j = i + 1;
            while (j < json.Length && (json[j] == ' ')) j++;
            int start = j;
            while (j < json.Length && (char.IsDigit(json[j]) || json[j] == '.' || json[j] == '-')) j++;
            double val;
            if (double.TryParse(json.Substring(start, j - start), System.Globalization.NumberStyles.Any,
                                CultureInfo.InvariantCulture, out val)) return val;
            return 0;
        }

        private static string ExtractJsonString(string json, string key)
        {
            string needle = "\"" + key + "\"";
            int i = json.IndexOf(needle, StringComparison.Ordinal);
            if (i < 0) return "";
            i = json.IndexOf(':', i + needle.Length);
            if (i < 0) return "";
            int q1 = json.IndexOf('"', i + 1);
            if (q1 < 0) return "";
            int q2 = json.IndexOf('"', q1 + 1);
            if (q2 < 0) return "";
            return json.Substring(q1 + 1, q2 - q1 - 1);
        }
    }
}
