#!/usr/bin/env python3
"""Build the deployable nixi role pack from audited templates.

The source Claude Code Skill is used only as a build-time provenance check.
Production xiaozhi-server loads only the generated package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Optional


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "main" / "xiaozhi-server" / "rolepacks" / "nixi"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_source(skill_root: Path, source_manifest: dict) -> None:
    failures = []
    for item in source_manifest["files"]:
        path = skill_root / item["path"]
        if not path.is_file():
            failures.append(f"missing: {item['path']}")
            continue
        actual_hash = sha256(path)
        actual_size = path.stat().st_size
        if actual_hash != item["sha256"] or actual_size != item["bytes"]:
            failures.append(
                f"drift: {item['path']} expected={item['sha256']}:{item['bytes']} "
                f"actual={actual_hash}:{actual_size}"
            )
    if failures:
        raise RuntimeError("nixi-roleplay source verification failed:\n" + "\n".join(failures))


def build(output: Path, skill_root: Optional[Path]) -> dict:
    source_manifest = load_json(SCRIPT_DIR / "source_manifest.json")
    if skill_root is not None:
        verify_source(skill_root.resolve(), source_manifest)

    template_root = SCRIPT_DIR / "templates"
    relative_files = [
        Path("pack.json"),
        Path("prompts/common.txt"),
        Path("prompts/wu.txt"),
        Path("prompts/chi.txt"),
        Path("prompts/duo.txt"),
    ]
    output.mkdir(parents=True, exist_ok=True)
    manifest_files = []
    for relative in relative_files:
        source = template_root / relative
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        manifest_files.append(
            {
                "path": relative.as_posix(),
                "sha256": sha256(target),
                "bytes": target.stat().st_size,
            }
        )

    manifest = {
        "artifact": "xiaozhi_rolepack",
        "schema_version": 1,
        "pack_id": "nixi",
        "version": "1.1.0",
        "pack_file": "pack.json",
        "files": manifest_files,
        "source": source_manifest,
        "build_properties": {
            "deterministic": True,
            "runtime_requires_authoring_skill": False,
            "runtime_writes": False,
            "tts_private_psychology": "disabled",
            "duo_audio": "single_tts_voice_with_spoken_speaker_labels",
            "daughter_profile": "manager_editable_session_fiction",
        },
    }
    manifest_path = output / "manifest.json"
    # 固定 LF：manifest 参与逐字节确定性校验，不能随平台换行符漂移。
    # 这里不用 Path.write_text(newline=...)，该参数需要 Python 3.10。
    with manifest_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skill-root",
        type=Path,
        help="Optional nixi-roleplay directory to verify before building",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        manifest = build(args.output.resolve(), args.skill_root)
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        f"built rolepack={manifest['pack_id']} files={len(manifest['files'])} "
        f"output={args.output.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
