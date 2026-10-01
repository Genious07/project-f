# Installation and local operation

The developer alpha is distributed as a Python wheel and source archive and includes a container entry point. The package has no third-party runtime dependencies. Rust is optional and provides the syntax frontend only.

## Build and install

Use Python 3.11, 3.12, 3.13, or 3.14. The hosted matrix covers those versions on Ubuntu and Python 3.14 on macOS. Windows is not part of the supported matrix yet.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install build==1.2.2.post1
.venv/bin/python -m build
python3 -m venv /tmp/foresee-user
/tmp/foresee-user/bin/python -m pip install --no-index --no-deps dist/*.whl
/tmp/foresee-user/bin/foresee init /tmp/my-catalog --demo-data
/tmp/foresee-user/bin/foresee run --project /tmp/my-catalog/foresee.json
```

No `PYTHONPATH` or source checkout is needed after installing the wheel. The sample paths must be unused. Omit `--demo-data` to initialize an empty prepared catalog. See [projects](projects.md) for importing rows, supplying plans, and selecting an entry point.

Build backend versions are pinned in `pyproject.toml`. The wheel contains the Python package and console entry point; the source archive also includes tests, fixtures, documentation, Rust sources, and conformance tools. No local databases or toolchains are packaged. Rebuilding a wheel from the same source with the same build tools and `SOURCE_DATE_EPOCH` produces matching bytes in the verified local environment. This is not a claim that arbitrary build environments or container layers are byte-identical.

```bash
SOURCE_DATE_EPOCH=1700000000 .venv/bin/python -m build --wheel
.venv/bin/python tools/verify_install.py dist/*.whl
```

The verification script installs without network access into a fresh virtual environment, clears source-path overrides, executes the full CLI workflow from a temporary directory, and checks cold backup/restore.

## Container

```bash
docker build -t project-f:local .
mkdir -p "$PWD/catalog-data"
docker run --rm --network=none --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$PWD/catalog-data,target=/data" \
  project-f:local init /data/project --demo-data
docker run --rm --network=none --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$PWD/catalog-data,target=/data" \
  project-f:local run --project /data/project/foresee.json
```

Use the same mount and `/data` location on later invocations of `inspect`, `replay`, and `reconcile`. Reports and journals contain absolute target paths. Data, receipts, reports, and journals persist in the mounted project directory after the container exits. No ports, external services, or model credentials are required.

The image runs as UID/GID 10001 by default. The example overrides that identity to match the owner of a host bind mount; either grant the default user write access or use the explicit override. Do not rely on the ephemeral container filesystem for data persistence. The image contains the installed Python wheel, not the Rust frontend. Its base image is pinned by digest; updating it is an explicit maintenance change.

```bash
python3 tools/verify_container.py project-f:local
```

This check starts seven separate network-disabled containers and verifies that one applied revision and receipt persist across them. Image building needs network access unless the base image and build dependencies are already cached.

## Backup and restore

Stop all workers and close database connections before a cold backup. Copy the entire project directory, including `catalog.db`, any SQLite sidecar files, `.foresee/runs.db`, reports, configuration, source, and candidate fixtures. Keep permissions restrictive because snapshots and prompts may be sensitive.

Restore that directory to the same absolute location or the same `/data` container mount path. Then run `reconcile` and `replay` against retained evidence before starting new work. Relocating an old journal to a different absolute target path is not supported automatically. Backing up only the target database loses run intent and report evidence. Copying live SQLite database files individually is not the verified backup workflow.

## CI and operational scope

The `Verify` GitHub Actions workflow runs Python tests and clean-wheel installation on the supported matrix, Rust tests/format/conformance on Ubuntu and macOS, and the container persistence check on Ubuntu. Built Python artifacts are attached to each successful packaging job. The workflow has read-only repository permissions and no model credentials or automatic publishing steps. Versioned release artifacts are published manually after the release gate passes.

Use this as a local developer CLI for the documented SQLite domain. It is not a hosted multi-tenant service or a security sandbox. Resource limits, evidence integrity, retry boundaries, and recovery limitations remain as documented in the domain contracts. The alpha is distributed through GitHub Releases; no PyPI package or container registry image is published yet.
