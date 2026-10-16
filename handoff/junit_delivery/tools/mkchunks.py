import hashlib, sys, os
parts_dir, out_dir = sys.argv[1], sys.argv[2]
P = lambda i: os.path.join(parts_dir, f"full_76a7211.junit.xml.xz.b64.part{i:02d}of11.txt")
src = b"".join(open(P(i), "rb").read() for i in range(1, 11))
joined = open(os.path.join(parts_dir, "full_76a7211.junit.xml.xz.b64.txt"), "rb").read()
assert joined[:len(src)] == src and joined[len(src):] == open(P(11), "rb").read()
assert hashlib.sha256(joined).hexdigest() == "2860ca4d4ac3deb25db073286deb72fc974cf59b20df039181ae61b9437b6639"
lines = src.splitlines(keepends=True)
assert all(len(l) == 77 for l in lines), set(len(l) for l in lines)
N = 104
groups = [lines[i:i+N] for i in range(0, len(lines), N)]
n = len(groups); off = 0; inv = []
for k, g in enumerate(groups, 1):
    data = b"".join(g)
    name = f"junit_b64_c{k:02d}of{n:02d}.txt"
    open(os.path.join(out_dir, name), "wb").write(data)
    inv.append((k, name, off, len(data), len(g), hashlib.sha256(data).hexdigest()))
    off += len(data)
assert off == len(src)
hdr = ["CHUNK_INVENTORY for full_76a7211.junit.xml.xz.b64 (replaces parts 01-10 of 11; part 11 unchanged)",
       f"source_bytes_parts01_10 {len(src)} sha256 {hashlib.sha256(src).hexdigest()}",
       f"part11 bytes {len(joined)-len(src)} sha256 {hashlib.sha256(joined[len(src):]).hexdigest()}",
       f"joined_b64 bytes {len(joined)} sha256 {hashlib.sha256(joined).hexdigest()}",
       "joined = chunks c01..c%02d in order + part11of11; xz sha256 7fc73618...; xml sha256 52a351c2dce9e3bfad9667ca36077c3503e96caa7354aaee9da20275a8799a54" % n,
       "index name offset length lines sha256"]
open(os.path.join(out_dir, "CHUNK_INVENTORY.txt"), "w").write("\n".join(hdr + [" ".join(map(str, r)) for r in inv]) + "\n")
with open(os.path.join(out_dir, "chunk_sums.txt"), "w") as f:
    for r in inv: f.write(f"{r[5]}  {r[1]}\n")
