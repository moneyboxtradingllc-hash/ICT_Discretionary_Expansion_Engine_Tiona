"""Offline, allowlisted excerpt of an EXISTING startup-proof record. Reads local files only: no network, no run.

    python3 -I stage5_proof_record_excerpt.py <proof stamp> <corrected stage5_startup_proof.zsh> <.env> [earlier stamp]

  <proof stamp>     e.g. 20261023T004424Z: reads ~/stage5_startup_proof_<stamp>/private/{proof_raw,proof_sanitized}.log
                    and ~/Desktop/stage5_startup_proof_SANITIZED_<stamp>.txt (all left untouched)
  <corrected ...>   the reviewed proof script at 579759e; only its Python extraction block is executed, on the
                    existing sanitized log, to produce a SEPARATE corrected summary. The shell wrapper is never run.
  <.env>            read only to refuse output that contains any account/credential value (values never printed)
  [earlier stamp]   optional: an earlier attempt whose Desktop summary supplies its start/end/exit line

Writes ~/Desktop/stage5_proof_record_excerpt_<stamp>.txt and prints it with its SHA-256. Fields that the record
does not contain are printed as UNKNOWN; nothing is inferred.
"""
import glob
import hashlib
import os
import re
import subprocess
import sys

CORRECTED_SHA = "574c926ddb0638bb548cd10fb4d420a1ecdd938e9ecdfdca61df838bf9f34c1b"
LABELS = ["ARM STATE", "ARMED", "LANE", "NEW ENTRY PERMITTED", "ACTIVE CONTRACT", "QUOTE CONSUMER",
          "EXECUTABLE BID/ASK", "CANDLE CONSUMER", "CANDLE CONTRACT", "QUOTE CONTRACT", "RECONNECTS OBSERVED",
          "ACCOUNT STILL FLAT", "SHUTDOWN"]
FRESHNESS = re.compile(r"fresh|stale|last trade|startup history|quote age|as of", re.I)
TROUBLE = re.compile(r"REFUSED|Traceback|Error|WATCHDOG|RECOVERY")


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest() if os.path.exists(path) else "UNKNOWN (file absent)"


def header_field(text, prefix):
    m = re.search(r"^" + re.escape(prefix) + r"\s*(.*)$", text, re.M)
    return m.group(1).strip() if m else "UNKNOWN"


def private_values(envp):
    vals = []
    for p in [envp] + sorted(glob.glob(envp + ".before_rebind_*")):
        for line in open(p, encoding="utf-8", errors="replace"):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if len(v) >= 4 and re.search(r"ACCOUNT|USERNAME|API_KEY|FINGERPRINT|PASSWORD|TOKEN|SECRET", k):
                    vals.append(v)
    return vals


def main():
    stamp, corrected, envp = sys.argv[1], sys.argv[2], sys.argv[3]
    earlier = sys.argv[4] if len(sys.argv) > 4 else ""
    home = os.path.expanduser("~")
    priv = f"{home}/stage5_startup_proof_{stamp}/private"
    raw, san = f"{priv}/proof_raw.log", f"{priv}/proof_sanitized.log"
    desk = f"{home}/Desktop/stage5_startup_proof_SANITIZED_{stamp}.txt"
    for p in (san, desk):
        if not os.path.exists(p):
            sys.exit(f"STOPPED: {p.replace(home, '~')} not found; nothing written")
    if sha(corrected) != CORRECTED_SHA:
        sys.exit("STOPPED: corrected proof script digest does not match 579759e; nothing written")

    summary = open(desk, encoding="utf-8", errors="replace").read()
    log = open(san, encoding="utf-8", errors="replace").read()
    start_line = header_field(summary, "start:")
    m = re.search(r"exit code:\s*(-?\d+)", start_line)
    rc = m.group(1) if m else "UNKNOWN"

    out = [f"STAGE5 STARTUP PROOF - ALLOWLISTED EXCERPT OF THE EXISTING RECORD (proof stamp {stamp})",
           "Derived offline from local files; no network request or run. Account names/ids/fingerprints,",
           "credentials, .env files/backups and raw logs are not included.", "",
           "== Digests of the originals (unchanged)",
           f"raw log (private)            : {sha(raw)}",
           f"sanitized log (private)      : {sha(san)}",
           f"Desktop sanitized summary    : {sha(desk)}",
           f"excerpt tool (this script)   : {sha(os.path.abspath(__file__))}",
           f"corrected summary script     : {CORRECTED_SHA} (579759e; only its Python extraction block executed)",
           "", "== Provenance",
           "sanitized log = raw log with every .env credential/account value replaced by [REDACTED], the home path",
           "  replaced by ~, Bearer tokens and JWTs redacted (stage5_startup_proof.zsh @ 7c59912, step 6).",
           "excerpt = lines of the sanitized log whose label is on a fixed allowlist, every occurrence, with line",
           "  numbers; header fields copied from the Desktop summary; nothing edited or inferred.",
           "", "== Run header (from the Desktop summary)"]
    for prefix in ("== preflight", "source:", "runtime:", "credentials:", "flags:", "command:", "start:",
                   "copied .env deleted after the run:"):
        out.append(f"{prefix} {header_field(summary, prefix)}")
    out.append(f"numeric exit code            : {rc}")

    out += ["", "== Allowlisted telemetry lines (sanitized log, every occurrence, line number: text)"]
    lines = log.splitlines()
    for label in LABELS:
        hits = [(i + 1, l.strip()) for i, l in enumerate(lines)
                if re.match(r"^\s*" + re.escape(label) + r"\s*:", l)]
        if not hits:
            out.append(f"{label}: UNKNOWN (not in the record)")
        for n, l in hits:
            out.append(f"  {n:>5}: {l}")
    banner = [(i + 1, l.strip()) for i, l in enumerate(lines) if "No order will be placed" in l]
    out += [f"  {n:>5}: {l}" for n, l in banner] or ["No-order banner: UNKNOWN (not in the record)"]
    fresh = [(i + 1, l.strip()) for i, l in enumerate(lines) if FRESHNESS.search(l) and len(l) < 200]
    out.append("Freshness/timestamp lines:" if fresh else "Freshness timestamps: UNKNOWN (no such line in the record)")
    out += [f"  {n:>5}: {l}" for n, l in fresh]
    trouble = [l for l in lines if TROUBLE.search(l)]
    out.append(f"Refusal/error/watchdog/recovery lines: {len(trouble)}"
               + ("" if not trouble else " (contents kept private)"))

    out += ["", "== Original verdict (preserved, from the Desktop summary)"]
    out += [l for l in summary.splitlines() if l.startswith("RESULT:")] or ["UNKNOWN"]

    out += ["", "== SEPARATE corrected summary: reviewed extraction block @ 579759e run on the existing sanitized log"]
    script = open(corrected, encoding="utf-8").read()
    block = script.split('$V/python - "$P/proof_sanitized.log" "$RC" > $P/summary_body.txt <<\'PYEOF\'\n', 1)[1]
    block = block.split("\nPYEOF\n", 1)[0]
    res = subprocess.run([sys.executable, "-I", "-c", block, san, rc if rc != "UNKNOWN" else "1"],
                         capture_output=True, text=True)
    out += [l for l in res.stdout.splitlines() if not re.match(r"ACCOUNT\s+:", l)]
    out.append(f"(extraction block sha256 {hashlib.sha256(block.encode()).hexdigest()}, exit {res.returncode})")

    if earlier:
        ed = f"{home}/Desktop/stage5_startup_proof_SANITIZED_{earlier}.txt"
        if os.path.exists(ed):
            et = open(ed, encoding="utf-8", errors="replace").read()
            out += ["", f"== Earlier attempt {earlier} (from its Desktop summary, digest {sha(ed)})",
                    f"start: {header_field(et, 'start:')}"]
            out += [l for l in et.splitlines() if l.startswith("RESULT:")] or ["RESULT: UNKNOWN"]

    text = "\n".join(out) + "\n"
    for v in private_values(envp):
        if v in text:
            sys.exit("STOPPED: a private .env value would appear in the excerpt; nothing written")
    if re.search(r"acct:[0-9a-f]{6}", text):
        sys.exit("STOPPED: a fingerprint-shaped value would appear in the excerpt; nothing written")
    dest = f"{home}/Desktop/stage5_proof_record_excerpt_{stamp}.txt"
    open(dest, "w", encoding="utf-8").write(text)
    print(text)
    print(f"excerpt file: {dest.replace(home, '~')}")
    print(f"excerpt sha256: {hashlib.sha256(text.encode()).hexdigest()}")


if __name__ == "__main__":
    main()
