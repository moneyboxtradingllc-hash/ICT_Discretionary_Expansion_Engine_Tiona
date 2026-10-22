# Operating Mac: final-source full run (operator-run, as printed; the username is redacted to OPERATOR)

    zsh ~/stage5_mac_verify.zsh ffe00aef3db7fb2339780ed0fa9016149923c96e full
    script sha256 ebedd3f76f3db3f38d759c56d553a297f046c16b8061e2ab8899464047d90878 (published at 3d99c5b)

    == Stage 5 Mac verification 20261022T001853Z  source ffe00aef3db7fb2339780ed0fa9016149923c96e  mode full
    ProductVersion: 10.14.6  BuildVersion: 18G103   uname: Darwin 18.7.0 x86_64
    cpu: Intel(R) Core(TM) i5-8210Y CPU @ 1.60GHz  rosetta_translated: 0   zsh: 5.3
    xcode_select: /Library/Developer/CommandLineTools   brew_prefix: none
    git: /usr/bin/git  git version 2.20.1 (Apple Git-117)
    using python: /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 (Python 3.12.7)
    head ffe00aef3db7fb2339780ed0fa9016149923c96e tree 57cc69c03882efc9bd1d6a7921f4fea6792a31cc
    pip install rc=0
    child: parent_git /usr/bin/git; child_path [<venv>/bin, /usr/local/bin, /usr/bin, /bin]; child_finds_git /usr/bin/git;
           env_names_equal_allowlist true; EXECUTION_ENABLED=false ALLOW_PAPER_ORDERS=false AI_BRAIN_LLM=false
           TWO_BRAIN_MODE=off HTTPS_PROXY=HTTP_PROXY=http://127.0.0.1:9
    ledger and protected-source verification: rc=0
    focused regression set: rc=0  179 passed in 2690.18s (0:44:50)
    complete suite: rc=0  9699 tests collected in 19.36s
    complete suite: rc=0  9116 passed, 583 skipped, 23 warnings, 34 subtests passed in 13055.74s (3:37:35)

    STAGE5 MAC SUMMARY
    source: head ffe00aef3db7fb2339780ed0fa9016149923c96e tree 57cc69c03882efc9bd1d6a7921f4fea6792a31cc
    clean_before_run: yes
    python: 3.12.7 | macOS-10.14.6-x86_64-i386-64bit | x86_64
    pins matching: 47 / 47 | mismatches: []
    ledger: LEDGER_VERIFIED
    focused.junit.xml: 179 cases, 179 passed, 0 skipped, 0 failed
    full.junit.xml: 9699 cases, 9116 passed, 583 skipped, 0 failed
    prior run stage5_mac_verify_20261021T025001Z source 5d18b4b...: 1336 cases, 24 skipped, 0 failure-only, 0 error-only, 0 failure+error nodes
    prior run stage5_mac_verify_20261021T165911Z source 5d18b4b...: 9694 cases, 583 skipped, 12 failure-only, 10 error-only, 0 failure+error nodes
    evidence: ~/Desktop/stage5_mac_results_20261022T001853Z.tar.gz  sha256 b5eb2303a358a0c068e8cb942241ea24f10512e38acb970679ba7e4732c79c25

The raw sanitized bundle contains the per-node JUnit, logs, NODE_ACCOUNTING.json, pins, inventory, clean status and
MANIFEST_SHA256. The operator sent it to Maurice by email in this thread. It contains no credentials, .env contents,
account identifiers or trading archives.
