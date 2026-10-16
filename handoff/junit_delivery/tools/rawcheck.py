import sys, json, base64, email, hashlib, os
raw_json, outdir, sums = sys.argv[1], sys.argv[2], sys.argv[3]
expect = {}
for line in open(sums):
    h, n = line.split(); expect[n] = h
j = json.load(open(raw_json))
raw = j["raw"]; raw += "=" * (-len(raw) % 4)
msg = email.message_from_bytes(base64.urlsafe_b64decode(raw))
print(j["id"], j["threadId"], j.get("labelIds"), "To:", msg["To"])
body = ""
for p in msg.walk():
    fn = p.get_filename()
    if fn:
        b = p.get_payload(decode=True); safe = os.path.basename(fn)
        open(os.path.join(outdir, safe), "wb").write(b)
        h = hashlib.sha256(b).hexdigest()
        ok = "MATCH" if expect.get(safe) == h else ("NOT-IN-LIST" if safe not in expect else "MISMATCH")
        print(" ", safe, len(b), h, ok)
    elif p.get_content_type() in ("text/plain", "text/html"):
        body += p.get_payload(decode=True).decode("utf-8", "replace")
import os
private = os.environ.get("PRIVATE_MARKER")
print("  private marker in body:", (private in body) if private else "unchecked", "| sign-off -tiona present:", "-tiona" in body)
