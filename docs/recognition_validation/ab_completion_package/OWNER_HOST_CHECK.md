# Owner-host (Windows) check

No Windows host was available to this engineering run, so a healthy fresh
Windows child launch is NOT claimed. On the owner host:

1. Use a disposable clone of branch `engineering/stage5-ab-completion-20261020`
   at commit 5d18b4b41b45e7f895aa6b1d3aa1fd5966c40e03. Do not use the
   operator checkout.
2. Run with the same allowlisted, network-denying runner used for the ten
   failures:

       python -m pytest -q -p no:cacheprovider tests/test_recognition_child_portability.py ^
         tests/test_recognition_process_isolation.py tests/test_recognition_quote_wake_trigger.py ^
         tests/test_recognition_scoring_cli.py

## Expected outcome

- **Expected:** the ten previously failing nodes pass, and
  `test_windows_names_do_not_widen_the_posix_child_allowlist` is SKIPPED on
  Windows by design. That skip is not a pass.
- **If a child still fails:** CHILD_STATUS.json `stderr_tail` names the next
  Windows-only limit. That limit remains UNPROVEN, and no guard may be
  weakened to get past it.

## Python version

requirements.txt (UTF-16) pins 47 packages but does not pin Python. The
supported runtime verified here is Linux with Python 3.12.3 and all 47 pins
exact.

On the owner host, 33 of the 47 pins differ (Python 3.14.5). Install the
pins exactly before treating a Windows result as more than a host result.
