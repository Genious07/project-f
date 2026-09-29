"""Install a wheel into a fresh venv and exercise it outside the checkout."""
import argparse
import json
import os
import shutil
import sqlite3
from contextlib import closing
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        venv.EnvBuilder(with_pip=True).create(root / "venv")
        binary = root / "venv" / ("Scripts" if os.name == "nt" else "bin")
        python = binary / ("python.exe" if os.name == "nt" else "python")
        cli = binary / ("foresee.exe" if os.name == "nt" else "foresee")
        subprocess.run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)], cwd=root, env=env, check=True)
        def run(*words):
            result = subprocess.run([str(cli), *map(str, words)], cwd=root, env=env, check=True, capture_output=True, text=True, timeout=30)
            return result.stdout
        project = root / "project"
        run("init", project, "--demo-data")
        run("check", project / "decision.fore")
        run("build", project / "decision.fore", "-o", root / "program.json")
        result = json.loads(run("run", "--project", project / "foresee.json"))
        assert result["outcome"]["status"] == "applied"
        assert json.loads(run("inspect", result["report"]))["checksum_valid"]
        assert json.loads(run("replay", result["report"]))["decision_reproduced"]
        assert json.loads(run("reconcile", result["journal"]))["runs"][0]["state"] == "completed"
        # Cold backup and restore to the same absolute location preserve journal references.
        shutil.copytree(project, root / "backup")
        project.rename(root / "retired")
        shutil.copytree(root / "backup", project)
        assert json.loads(run("reconcile", result["journal"]))["runs"][0]["state"] == "completed"
        with closing(sqlite3.connect(project / "catalog.db")) as db, db:
            assert db.execute("SELECT revision FROM catalog_meta").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM foresee_receipts").fetchone()[0] == 1
        print("PASS: clean wheel install, CLI workflow, persisted data, and cold backup/restore")


if __name__ == "__main__":
    main()
