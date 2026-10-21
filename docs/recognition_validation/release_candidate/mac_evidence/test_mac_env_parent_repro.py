"""Parent reproducer: the owner-Mac child condition against the real child of the checked-out source."""
import json
import test_recognition_process_isolation as ISO
import test_recognition_scoring_cli as SCLI
from recognition_validation import child as CH

world = SCLI.world
_short_schedule = ISO._short_schedule
MACOS_INJECTED = {"LC_CTYPE": "UTF-8", "__CF_USER_TEXT_ENCODING": "0x1F5:0x0:0x0"}


def test_mac_condition(world, tmp_path):
    status = CH.run_in_child(ISO._request(world, tmp_path, "mac"), out_root=tmp_path / "mac", extra_env=MACOS_INJECTED)
    print("MAC_CONDITION_RESULT", json.dumps({"complete": status["complete"],
                                               "child_exit_status": (status["child_exit"] or {}).get("status"),
                                               "child_exit_code": (status["child_exit"] or {}).get("code"),
                                               "detail": (status["child_exit"] or {}).get("detail")}))
