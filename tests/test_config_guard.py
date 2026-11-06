"""load_config safety guards: a placeholder device key must never boot
(GitHub issue #2 regression), and missing token files are skipped.

  python3 tests/test_config_guard.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rotator as R


def _load_with(cfg: dict):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "tokens").mkdir()
    (tmp / "tokens" / "a.token").write_text("sk-ant-oat01-test")
    (tmp / "config.json").write_text(json.dumps(cfg))
    old_cfg, old_root = R.CONFIG_PATH, R.ROOT
    R.CONFIG_PATH, R.ROOT = tmp / "config.json", tmp
    try:
        return R.load_config()
    finally:
        R.CONFIG_PATH, R.ROOT = old_cfg, old_root


ACCT = [{"name": "a", "token_file": "tokens/a.token"}]


def test_placeholder_device_key_refuses_startup():
    try:
        _load_with({"accounts": ACCT,
                    "devices": {"my-laptop": "dev-my-laptop-REPLACE-WITH-RANDOM-HEX"}})
        raise AssertionError("placeholder key must refuse startup")
    except SystemExit as e:
        assert "placeholder" in str(e), str(e)


def test_real_keys_boot():
    cfg = _load_with({"accounts": ACCT, "devices": {"laptop": "dev-laptop-a1b2c3"}})
    assert cfg["accounts"][0]["token"] == "sk-ant-oat01-test"


def test_missing_token_file_is_skipped_not_fatal():
    cfg = _load_with({"accounts": ACCT + [{"name": "b", "token_file": "tokens/nope.token"}],
                      "devices": {"laptop": "dev-laptop-a1b2c3"}})
    assert [a["name"] for a in cfg["accounts"]] == ["a"]


def test_empty_and_duplicate_device_keys_refuse_startup():
    for devices in ({"device": ""}, {"device": "   "}, {"device": None},
                    {"one": "same", "two": "same"}, None):
        try:
            _load_with({"accounts": ACCT, "devices": devices})
            raise AssertionError("invalid device keys must refuse startup")
        except SystemExit as error:
            assert "device" in str(error)


def test_account_weight_must_be_a_positive_number():
    devices = {"laptop": "dev-laptop-a1b2c3"}
    for w in (0, -1, "1", True):
        try:
            _load_with({"accounts": [dict(ACCT[0], weight=w)], "devices": devices})
            raise AssertionError(f"weight {w!r} must refuse startup")
        except SystemExit as error:
            assert "weight" in str(error)
    _load_with({"accounts": [dict(ACCT[0], weight=0.25)], "devices": devices})


def test_account_weekly_cap_must_be_a_number_from_0_to_1():
    devices = {"laptop": "dev-laptop-a1b2c3"}
    for cap in (-0.1, 1.5, "0.5", True, None):
        try:
            _load_with({"accounts": [dict(ACCT[0], weekly_cap=cap)], "devices": devices})
            raise AssertionError(f"weekly_cap {cap!r} must refuse startup")
        except SystemExit as error:
            assert "account 'a'" in str(error) and "weekly_cap" in str(error), str(error)
    for cap in (0, 0.5, 1):
        _load_with({"accounts": [dict(ACCT[0], weekly_cap=cap)], "devices": devices})


def test_account_cap_lookahead_must_parse():
    devices = {"laptop": "dev-laptop-a1b2c3"}
    for value in ("12", "1.5h", "12x", "", 12, None):
        try:
            _load_with({"accounts": [dict(ACCT[0], cap_lookahead=value)], "devices": devices})
            raise AssertionError(f"cap_lookahead {value!r} must refuse startup")
        except SystemExit as error:
            assert "account 'a'" in str(error) and "cap_lookahead" in str(error), str(error)
    for value in ("30m", "12h", "2d"):
        _load_with({"accounts": [dict(ACCT[0], cap_lookahead=value)], "devices": devices})


def _import_with(cfg: dict, code: str = "import rotator"):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "tokens").mkdir()
    (tmp / "tokens" / "a.token").write_text("sk-ant-oat01-test")
    (tmp / "config.json").write_text(json.dumps(
        {"accounts": ACCT, "devices": {"laptop": "dev-laptop-a1b2c3"}, **cfg}))
    return subprocess.run([sys.executable, "-c", code], cwd=Path(R.__file__).parent,
                          text=True, capture_output=True,
                          env={**os.environ, "CLAUDE_ROTATE_CONFIG": str(tmp / "config.json")})


def test_panel_tailnet_needs_loopback_bind_and_a_bool():
    # Off loopback, any client could send Tailscale-User-Login itself.
    for cfg in ({"panel_tailnet": True, "bind": "0.0.0.0"},
                {"panel_tailnet": True, "bind": "100.101.102.103"},
                {"panel_tailnet": "false"}):
        child = _import_with(cfg)
        assert child.returncode != 0 and "panel_tailnet" in child.stderr, (cfg, child.stderr)
    child = _import_with({"panel_tailnet": True, "bind": "127.0.0.1"})
    assert child.returncode == 0, child.stderr


def test_refresh_idle_model_defaults_configures_and_must_be_a_nonempty_string():
    show = "import json, rotator; print(json.loads(rotator.REFRESH_BODY)['model'])"
    for cfg, model in (({}, "claude-haiku-4-5"),
                       ({"refresh_idle_model": "claude-haiku-5-5"}, "claude-haiku-5-5")):
        child = _import_with(cfg, show)
        assert child.returncode == 0 and child.stdout.strip() == model, (cfg, child.stderr)
    for bad in ("", "  ", 12, None, ["x"]):
        child = _import_with({"refresh_idle_model": bad})
        assert child.returncode != 0 and "refresh_idle_model" in child.stderr, (bad, child.stderr)


def test_top_level_cap_lookahead_defaults_to_12h_and_must_parse():
    show = "import rotator; print(rotator.CAP_LOOKAHEAD_S)"
    for cfg, seconds in (({}, 43200), ({"cap_lookahead": "2d"}, 172800),
                         ({"cap_lookahead": "30m"}, 1800)):
        child = _import_with(cfg, show)
        assert child.returncode == 0 and child.stdout.strip() == str(seconds), (cfg, child.stderr)
    for bad in ("bogus", "12", 12, None):
        child = _import_with({"cap_lookahead": bad})
        assert child.returncode != 0 and "cap_lookahead" in child.stderr, (bad, child.stderr)


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    for n, f in fns:
        f()
        print(f"ok   {n}")
    print(f"{len(fns)} passed")
