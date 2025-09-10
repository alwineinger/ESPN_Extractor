import sys
import types
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

# Stub out bot_daily_analysis to avoid heavy imports
module = types.ModuleType("bot_daily_analysis")
module.load_config = lambda: None
sys.modules["bot_daily_analysis"] = module

import daily_ai_summary as das


class DummyCfg:
    pushover_api_token = "t"
    pushover_user_key = "u"


def test_extract_action_priorities():
    reply = """## Current Week Recommendations\nX\n\n## Action Priorities (Summary)\n- First\n- Second\n\n## Season-Long Strategy\nY"""
    assert das.extract_action_priorities(reply) == "- First\n- Second"


def test_send_pushover_truncates(monkeypatch, tmp_path):
    captured = {}

    def fake_post(url, data, files, timeout):
        captured['data'] = data
        class R:
            def raise_for_status(self):
                pass
        return R()

    monkeypatch.setattr(das.requests, 'post', fake_post)

    attachment = tmp_path / "dummy.md"
    attachment.write_text("test")

    long_actions = "\n".join(["- action" + str(i) + " " + "x" * 200 for i in range(50)])
    reply = f"## Action Priorities (Summary)\n{long_actions}"
    das.send_pushover(DummyCfg(), reply, attachment)
    msg = captured['data']['message']
    assert len(msg) <= 1024
    assert 'Not all actions included' in msg
    assert msg.startswith('Action Priorities:')
