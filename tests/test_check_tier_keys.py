"""TDD tests for check_tier_keys.py (run: python3 -m pytest tests/)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_tier_keys import main  # noqa: E402

KEYS = {"a@t.io": "3aafdca9deadbeef", "b@t.io": "01234567cafe1234", "c@t.io": "cafe1234cafe1234"}
PW = "hunter2-super-secret-pw"
MAP = {"P0-public": "a@t.io", "P1-contract": "b@t.io", "P2-local": "c@t.io"}


def write_creds(cred_dir: Path, emails=None):
    cred_dir.mkdir(exist_ok=True)
    for email, key in KEYS.items():
        if emails is None or email in emails:
            (cred_dir / f"{email}.json").write_text(
                json.dumps({"email": email, "password": PW, "api_key": key}))


def run(capsys, tmp_path, data, cred_dir):
    m = tmp_path / "map.json"
    m.write_text(json.dumps(data))
    code = main(["--map", str(m), "--credentials-dir", str(cred_dir)])
    return code, *capsys.readouterr()


def test_all_tiers_ok(capsys, tmp_path):
    creds = tmp_path / "c"
    write_creds(creds)
    code, out, err = run(capsys, tmp_path, MAP, creds)
    assert code == 0 and err == ""
    for key in KEYS.values():
        assert f"{key[:8]}\u2026" in out  # fingerprint printed
        assert key not in out             # full key never printed


def test_missing_credentials_file(capsys, tmp_path):
    creds = tmp_path / "c"
    write_creds(creds, emails=["a@t.io", "b@t.io"])  # c@t.io missing
    code, _, err = run(capsys, tmp_path, MAP, creds)
    assert code == 2
    assert "P2-local" in err


def test_credentials_without_api_key(capsys, tmp_path):
    creds = tmp_path / "c"
    write_creds(creds)
    (creds / "b@t.io.json").write_text(
        json.dumps({"email": "b@t.io", "password": PW}))
    code, _, err = run(capsys, tmp_path, MAP, creds)
    assert code == 2
    assert "P1-contract" in err


def test_unknown_tier_key(capsys, tmp_path):
    creds = tmp_path / "c"
    write_creds(creds)
    code, _, err = run(capsys, tmp_path, {**MAP, "P9": "x@t.io"}, creds)
    assert code == 3
    assert "P9" in err


def test_password_never_printed(capsys, tmp_path):
    creds = tmp_path / "c"
    write_creds(creds, emails=["a@t.io"])  # partial -> exit 2 path too
    code, out, err = run(capsys, tmp_path, MAP, creds)
    assert code == 2
    assert PW not in out + err


def test_default_map_prefers_local_when_present(capsys, tmp_path, monkeypatch):
    # the e2e driver (and the operator) invoke the checker bare; when the
    # host-local map exists it must win over the placeholder template —
    # the template stays placeholder-only in git, the real mapping is
    # tier_keys.local.json (gitignored, host-local secret)
    here = tmp_path / "repo"
    here.mkdir()
    write_creds(here / "credentials")
    (here / "tier_keys.template.json").write_text(json.dumps(
        {"P0-public": "<fill@tier>", "P1-contract": "<fill@tier>",
         "P2-local": "<fill@tier>"}))
    (here / "tier_keys.local.json").write_text(json.dumps(MAP))
    import check_tier_keys as m
    monkeypatch.setattr(m, "__file__", str(here / "check_tier_keys.py"))
    code = m.main([])
    out, err = capsys.readouterr()
    assert code == 0, err
    assert "<fill@tier>" not in out


def test_default_map_falls_back_to_template(capsys, tmp_path, monkeypatch):
    # no local map -> the template is checked (placeholders -> rc 2 with
    # the named missing tiers; the committed default stays honest)
    here = tmp_path / "repo"
    here.mkdir()
    (here / "tier_keys.template.json").write_text(json.dumps(
        {"P0-public": "<fill@tier>", "P1-contract": "<fill@tier>",
         "P2-local": "<fill@tier>"}))
    (here / "credentials").mkdir()
    import check_tier_keys as m
    monkeypatch.setattr(m, "__file__", str(here / "check_tier_keys.py"))
    code = m.main([])
    _, err = capsys.readouterr()
    assert code == 2
    assert "P0-public" in err
