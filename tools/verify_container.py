"""Verify persistent project state across separate container invocations."""
import argparse
import json
import os
import sqlite3
from contextlib import closing
import subprocess
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        command = ["docker", "run", "--rm", "--network=none", "--user", f"{os.getuid()}:{os.getgid()}",
                   "--mount", f"type=bind,source={root},target=/data", args.image]
        def run(*words):
            return subprocess.run([*command, *words], check=True, capture_output=True, text=True, timeout=60).stdout
        run("init", "/data/project", "--demo-data")
        run("check", "/data/project/decision.fore")
        run("build", "/data/project/decision.fore", "-o", "/data/program.json")
        result = json.loads(run("run", "--project", "/data/project/foresee.json"))
        assert result["outcome"]["status"] == "applied"
        assert json.loads(run("inspect", result["report"]))["checksum_valid"]
        assert json.loads(run("replay", result["report"]))["decision_reproduced"]
        assert json.loads(run("reconcile", result["journal"]))["runs"][0]["state"] == "completed"
        with closing(sqlite3.connect(root / "project/catalog.db")) as db, db:
            assert db.execute("SELECT revision FROM catalog_meta").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM foresee_receipts").fetchone()[0] == 1
        print("PASS: seven network-disabled containers shared persistent data and evidence")


if __name__ == "__main__":
    main()
