#!/usr/bin/env python3
"""Build a self-contained Arduino App Lab .zip for import.

An App Lab app deployed via .zip import must be self-contained: only the app's
own files land on the board. This repo keeps the gateway logic in the shared
``services/`` package (used by the Docker stack and tests), so this script
*vendors* a copy of the needed modules into ``python/services/`` inside a
staging copy of ``app/`` and zips it. ``services/`` stays the single source of
truth; the vendored copy is only ever produced here (never committed).

The zip has ``app.yaml`` at its root:

    app.yaml, config.json, README.md, python/, sketch/, assets/
    python/services/{gateway,s7_simulator}/...   <- vendored

Usage:  python scripts/build_applab_zip.py [output.zip]
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
SERVICES = REPO_ROOT / "services"
# Only these service subpackages are needed at runtime by the App Lab app.
VENDOR_PACKAGES = ["gateway", "s7_simulator"]

DEFAULT_OUTPUT = REPO_ROOT / "dist" / "s7-opcua-gateway-applab.zip"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")
# The vendored copy needs only Python modules — leave Docker-stack cruft behind.
IGNORE_VENDOR = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "Dockerfile", "requirements.txt", "config.json"
)


def stage(staging: Path) -> None:
    # App files (app.yaml at the staging root == zip root).
    for name in ("app.yaml", "config.json", "README.md"):
        shutil.copy2(APP_DIR / name, staging / name)
    for folder in ("python", "sketch", "assets"):
        shutil.copytree(APP_DIR / folder, staging / folder, ignore=IGNORE)

    # Vendor the shared services into python/services so `from services...`
    # imports resolve on the board with no repo present.
    vendor_root = staging / "python" / "services"
    vendor_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SERVICES / "__init__.py", vendor_root / "__init__.py")
    for pkg in VENDOR_PACKAGES:
        shutil.copytree(SERVICES / pkg, vendor_root / pkg, ignore=IGNORE_VENDOR)


def make_zip(staging: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(staging))


def main() -> None:
    output = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_OUTPUT
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "app"
        staging.mkdir()
        stage(staging)
        make_zip(staging, output)

    size_kb = output.stat().st_size / 1024
    print(f"Built {output}  ({size_kb:.0f} KB)")
    print("Import it in App Lab via 'Import from ZIP'.")


if __name__ == "__main__":
    main()
