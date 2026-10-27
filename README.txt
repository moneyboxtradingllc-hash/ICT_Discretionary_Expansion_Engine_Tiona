LOCAL-AUTHORITY-20261026 complete engineering return (Missions 1-3). DISABLED BY DEFAULT; NO TRADING.
Parent ec8197ec5411fcbcae5b25ba5a4c395f82c122cc -> final 6e30453b70022ee66240716b72683b798ad4f523
Branch review/local-authority-chronology-20261026 (two commits: e49cd3a Mission 1, 6e30453 Missions 2-3).
Start with 00_RETURN.md. 01_*.patch = diffs; 02_source.bundle = portable git bundle (ec8197e..branch);
03_ledger_verification.json; evidence/ = real-tape walk tables, full-session event lists, C2 adjudication and the
scripts that regenerate them (evidence/regenerate.sh <tree> <outdir>); default_off/ = parent-vs-final projections;
mutants/ = activated mutant runner + results; suite/ = collect list, shard plan, 16 shard logs + JUnit, merged JUnit,
union accounting, isolated reruns. Paths under the build machine's scratch area are written as [scratch].
