from __future__ import annotations

import argparse
import json
import stat
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ROOT_FILES = (
    "server.py",
    "run.bat",
    "run.command",
    "requirements.txt",
    "README.md",
    "LICENSE",
)
ROOT_DIRECTORIES = ("tools", "web", "templates", "images", "docs")
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def iter_release_files():
    for relative in ROOT_FILES:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"Required release file is missing: {relative}")
        yield path, Path(relative)

    for directory in ROOT_DIRECTORIES:
        source = ROOT / directory
        if not source.is_dir():
            raise FileNotFoundError(f"Required release directory is missing: {directory}")
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            if relative.parts[:2] == ("images", "legacy"):
                continue
            if "__pycache__" in relative.parts or path.suffix in EXCLUDED_SUFFIXES:
                continue
            yield path, relative


def build_release(version: str, output: Path) -> None:
    manifest = json.loads((ROOT / "web" / "assets" / "versions.json").read_text(encoding="utf-8"))
    if manifest.get("suite") != version:
        raise ValueError(
            f"Requested release {version} does not match suite version {manifest.get('suite')!r}"
        )

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing archive: {output}")

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, relative in iter_release_files():
            info = zipfile.ZipInfo.from_file(source, relative.as_posix())
            info.create_system = 3
            permissions = 0o755 if relative.as_posix() == "run.command" else 0o644
            info.external_attr = (stat.S_IFREG | permissions) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with source.open("rb") as handle:
                archive.writestr(info, handle.read(), compresslevel=9)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the WD Wireless Tools release archive.")
    parser.add_argument("--version", required=True, help="Suite version without the leading v")
    parser.add_argument("--output", required=True, type=Path, help="Destination ZIP path")
    args = parser.parse_args()
    build_release(args.version, args.output)


if __name__ == "__main__":
    main()
