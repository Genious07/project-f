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
    parser.add_argument("--evidence", action="store_true", help="also install the evidence extra and test signatures")
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
        if os.name == "posix":
            # Exercise the installed worker from outside the repository, without a key.
            smoke = """
from foresee.catalog import Snapshot
from foresee.model_provider import ProposalFailure
from foresee.openai_provider import OpenAIConfig, openai_provider
provider = openai_provider(OpenAIConfig('test-model', 100, 100, 1, 1, 10))
try:
    provider.propose(Snapshot(0, (), 'test'), 'repair', 1)
except ProposalFailure as error:
    assert error.code == 'missing_credentials', error.code
else:
    raise AssertionError('worker unexpectedly succeeded')
"""
            subprocess.run([str(python), "-c", smoke], cwd=root,
                           env={**env, "OPENAI_API_KEY": ""}, check=True, timeout=20)
        subprocess.run([str(python), "-m", "foresee.conformance"], cwd=root, env=env, check=True, timeout=30)
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
        shutil.copyfile(Path(__file__).resolve().parents[1] / "tests/test_bounded_replay.py",
                        root / "test_bounded_replay.py")
        subprocess.run([str(python), "-m", "unittest", "test_bounded_replay", "-v"],
                       cwd=root, env=env, check=True, timeout=30)
        print("PASS: installed bounded replay tests (Linux resource tests require Linux)")

        if args.evidence:
            subprocess.run([str(python), "-m", "pip", "install", str(wheel) + "[evidence]"],
                           cwd=root, env=env, check=True, timeout=180)
            # Copy only the standalone tests: imports must resolve to the installed wheel.
            shutil.copyfile(Path(__file__).resolve().parents[1] / "tests/test_evidence_auth.py",
                            root / "test_evidence_auth.py")
            subprocess.run([str(python), "-m", "unittest", "test_evidence_auth", "-v"],
                           cwd=root, env=env, check=True, timeout=30)
            shutil.copyfile(Path(__file__).resolve().parents[1] / "tests/test_evidence_workflow.py",
                            root / "test_evidence_workflow.py")
            subprocess.run([str(python), "-m", "unittest", "test_evidence_workflow", "-v"],
                           cwd=root, env=env, check=True, timeout=30)
            shutil.copyfile(Path(__file__).resolve().parents[1] / "tests/test_evidence_cli.py",
                            root / "test_evidence_cli.py")
            subprocess.run([str(python), "-m", "unittest", "test_evidence_cli", "-v"],
                           cwd=root, env=env, check=True, timeout=60)
            print("PASS: installed evidence extra, signatures, and trust rejection tests")



if __name__ == "__main__":
    main()
