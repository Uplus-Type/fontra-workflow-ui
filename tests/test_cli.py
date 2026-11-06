import json
import subprocess
import sys

from fontra_workflow_ui.cli import main


def test_list_actions_text(capsys):
    assert main(["list-actions"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("input actions (")
    assert "\n  subset-glyphs\n" in out
    assert "- scaleFactor: a number, required" in out
    assert "- glyphNamesFile: a string or nothing, default null, path" in out


def test_list_actions_one_type(capsys):
    assert main(["list-actions", "--type", "input"]) == 0
    out = capsys.readouterr().out
    assert "fontra-read" in out
    assert "filter actions" not in out


def test_list_actions_json(capsys):
    assert main(["list-actions", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data["actions"]) == {"input", "filter", "output"}
    scale = next(a for a in data["actions"]["filter"] if a["name"] == "scale")
    assert scale["arguments"]["required"] == ["scaleFactor"]


def test_validate(tmp_path, capsys):
    good = tmp_path / "good.yaml"
    good.write_text(
        "steps:\n- input: fontra-read\n  source: '{family}.fontra'\n"
        "- output: fontra-write\n  destination: out.fontra\n"
    )
    assert main(["validate", str(good)]) == 0
    assert capsys.readouterr().out == "ok (variables: family)\n"

    bad = tmp_path / "bad.yaml"
    bad.write_text("steps:\n- filter: scale\n")
    assert main(["validate", str(bad)]) == 1
    assert capsys.readouterr().out == (
        "steps[0] (filter: scale), argument 'scaleFactor': required argument missing\n"
    )

    assert main(["validate", str(bad), "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False
    assert data["errors"][0]["argument"] == "scaleFactor"


def test_validate_with_substitutions(tmp_path, capsys):
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text("steps:\n- filter: scale\n  scaleFactor: '{f}'\n")
    assert main(["validate", str(recipe), "--substitute", "f:2"]) == 0
    assert main(["validate", str(recipe), "--substitute", "f:big"]) == 1


def test_module_runs_as_a_command():
    result = subprocess.run(
        [sys.executable, "-m", "fontra_workflow_ui.cli", "list-actions", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["schemaVersion"] == 1
