import json

from routelens import cli


def test_cli_db_path_comes_from_environment(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "env.db"
    monkeypatch.setenv("ROUTELENS_DATABASE", str(db_path))
    seen = {}

    def fake_run_all_checks(store):
        seen["db_path"] = store.db_path
        return []

    monkeypatch.setattr(cli, "run_all_checks", fake_run_all_checks)

    exit_code = cli.main(["--json"])

    assert exit_code == 0
    assert seen["db_path"] == db_path
    assert json.loads(capsys.readouterr().out) == []


def test_cli_db_flag_overrides_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUTELENS_DATABASE", str(tmp_path / "env.db"))
    flag_path = tmp_path / "flag.db"
    seen = {}

    def fake_run_all_checks(store):
        seen["db_path"] = store.db_path
        return []

    monkeypatch.setattr(cli, "run_all_checks", fake_run_all_checks)

    cli.main(["--db", str(flag_path), "--json"])

    assert seen["db_path"] == flag_path
