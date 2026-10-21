# Operating Mac: operator-run results, as returned to engineering

The operator ran these on the Mac. The username in paths is redacted to OPERATOR. The full evidence archives
(`stage5_mac_results_20261021T165911Z.tar.gz`, sha256 fd1b7b8c11bdab90d43e39d8e316cf038c604401a0917a60b20814ea023f6911,
and `stage5_mac_results_20261021T223327Z.tar.gz`, sha256
f174d3a4c19f27ff8540537039b2fff17772832f0c5780fd381fa9f718f5dec3) are held privately by the operator and are not
committed here.

## Host

- macOS 10.14.6 (18G103), Darwin 18.7.0 x86_64.
- Intel Core i5-8210Y at 1.60GHz, not translated by Rosetta.
- zsh 5.3, with Command Line Tools at /Library/Developer/CommandLineTools and no Homebrew.
- git 2.20.1 (Apple Git-117) at /usr/bin/git.
- Python 3.12.7 (python.org framework, /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12).

## Run 1: source 5d18b4b, mode full (16:59Z)

- pip install rc=0. Pins match 47/47.
- The child finds /usr/bin/git, and env equals the allowlist.
- Disarmed: EXECUTION_ENABLED=false, ALLOW_PAPER_ORDERS=false, AI_BRAIN_LLM=false, TWO_BRAIN_MODE=off,
  HTTP(S)_PROXY=http://127.0.0.1:9.
- LEDGER_VERIFIED.

| Set | Cases | Passed | Skipped | Failed | Errors | Time |
|---|---|---|---|---|---|---|
| Focused | 166 | 154 | 0 | 12 | 0 | 29m49s |
| Full | 9,694 | 9,089 | 583 | 22 | 10 | 3h18m29s |

The failures were:

- 10 process-isolation, quote-wake and scoring-CLI child launches, plus 2 portability child launches. The cause was
  CHILD_ENV_NOT_ALLOWLISTED.
- 10 ledger tests (`git init -b` is not available in git 2.20).

## Diagnosis on the Mac

The operator ran:

    env -i PATH=/usr/bin:/bin ../venv/bin/python3 -I -c 'import os; print(sorted(os.environ))'
    -> ['LC_CTYPE', 'PATH', '__CF_USER_TEXT_ENCODING']

In focused.log, CHILD_ENV_NOT_ALLOWLISTED appears in the child exits.

## Run 2: source 77769dc, mode focused (22:33Z)

The pins, child Git, environment, disarmed flags and ledger results are as in run 1.

| Set | Cases | Passed | Skipped | Failed | Time |
|---|---|---|---|---|---|
| Focused, now including the ledger tests | 179 | 178 | 0 | 1 | 42m51s |

The one failure was `test_macos_injected_names_reach_a_complete_child_and_foreign_values_are_refused`, with
`assert (True is False)`. The forged-`__CF_USER_TEXT_ENCODING` child completed because macOS rewrote the forged value.

## Run 3: source bdd852d, targeted

`tests/test_recognition_child_portability.py` and `tests/test_recognition_ledger.py`, run in the same emptied,
disarmed environment, gave **19 passed** (4m58s).
