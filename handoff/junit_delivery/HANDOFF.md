# Handoff: JUnit chunk delivery to Maurice (continue from J3)

You are continuing as Tiona's engineering assistant. Mail is sent from tionariveracollabs@gmail.com.
- Plain-text bodies only, signed exactly `-tiona` on the last line.
- Never write the owner's personal address anywhere; the session prompt names it. Set PRIVATE_MARKER to it when running rawcheck.py.
- Standing authorization from Tiona: do the work and send without asking.

## Where things stand (2026-10-16 ~18:15 UTC)

- **Composition handoff: done.** C1–C5 were sent in the thread below and RAW-verified byte-exact. C4 needed one resend; the resend matches.
- **JUnit replacement: in progress.**
  - The 25 chunks in `chunks/` replace parts 01–10 of `full_76a7211.junit.xml.xz.b64`. Part 11 is unchanged and Maurice already verified it.
  - `chunks/CHUNK_INVENTORY.txt` gives index, name, offset, length, line count and sha256 for each chunk.
  - **J1 (c01, c02) and J2 (c03, c04) are sent and verified.**
  - **Next is J3 = c05 + c06.**
  - Total is J1..J13, two chunks per email; J13 carries c25 only.

## Thread

- Thread id: `1a1429ae4e1293c8`.
- Reply with `mcp__Gmail__reply`, using messageId `1a1429ae4e1293c8` (Maurice's 02:46Z message) and the default recipient (moneyboxtradingllc@gmail.com).

## Per-email procedure (repeat for J3..J13)

1. Base64 the two chunk files with `base64 -w0 chunks/junit_b64_cNNof25.txt`. The attachment `content` is the base64 of the file bytes.
2. Reply with:
   - attachments `junit_b64_cNNof25.txt`, mimeType `text/plain`;
   - this body:
     ```
     JUNIT Jk of 13 - chunks cNN and cMM of 25

     Maurice,

     VERIFIED-RUN: J(k-1) arrived byte-exact. <chunk> (<sha8>...) and <chunk> (<sha8>...) both match CHUNK_INVENTORY.txt.

     Attached (text/plain):
     - junit_b64_cNNof25.txt: offset <off>, <len> bytes, <lines> lines, sha256 <full sha>
     - junit_b64_cMMof25.txt: offset <off>, <len> bytes, <lines> lines, sha256 <full sha>

     -tiona
     ```
3. RAW-verify the sent message:
   - Fetch it with `mcp__Gmail__get_message` (messageFormat RAW). The result is saved to a tool-results file.
   - Run `python3 -I tools/rawcheck.py <that file> <empty outdir> verify_sums.txt`.
   - Each attachment must print MATCH.
4. If a chunk prints MISMATCH:
   - mention it in the next email: say which chunk, and the received vs expected sha;
   - re-attach it under the same name in that next email.

   Copying base64 by hand occasionally changes one character, so always check.
5. After J13 verifies, send one final short email. It should state:
   - all 25 chunks were received byte-exact, each with its sha;
   - the rebuild command:
     ```
     cat junit_b64_c{01..25}of25.txt full_76a7211.junit.xml.xz.b64.part11of11.txt > j.b64 && base64 -d j.b64 > full_76a7211.junit.xml.xz && xz -dk full_76a7211.junit.xml.xz
     ```
   - the expected hashes: joined sha256 2860ca4d4ac3deb25db073286deb72fc974cf59b20df039181ae61b9437b6639; xz 7fc736184de6c0c07fbaa63809e4a6eb9bffcfc2ce3f166c155fc7c1127a9321; XML 52a351c2dce9e3bfad9667ca36077c3503e96caa7354aaee9da20275a8799a54.

## Ongoing

- Every 30 minutes, check Gmail (`from:moneyboxtradingllc@gmail.com newer_than:1d`) for new mail from Maurice.
  - Answer anything new in its own thread, using the same rules.
  - Re-arm the check with `mcp__Claude_Code_Remote__send_later` (30 minutes).
- Label every claim VERIFIED-RUN / VERIFIED-CODE / INFERRED / UNKNOWN.
- Prohibited: trading, arming, orders, deployment, live provider/venue/model calls, credentials, merges, force-pushes, and any change to the operator checkout.
- The engineering work lives on branch `review/reversal-foundation-wip-20261006` (head f5934c0). Don't change it unless Maurice asks for engineering work.
