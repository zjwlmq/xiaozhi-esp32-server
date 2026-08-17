"""Load compact, deployment-safe role packs from a short system-prompt directive.

The manager UI only needs to store a directive such as::

    @rolepack nixi/wu
    canon=novel
    stage=S7

Role-pack files are shipped with xiaozhi-server.  The original authoring Skill is
therefore not required inside a Docker container or on the production host.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


ROLEPACK_DIRECTIVE_RE = re.compile(
    r"^@rolepack\s+(?P<pack>[a-z0-9][a-z0-9_-]*)/(?P<mode>[a-z0-9][a-z0-9_-]*)$"
)
OPTION_RE = re.compile(r"^(?P<key>[a-z_][a-z0-9_]*)=(?P<value>[^\r\n]+)$")
SAFE_VALUE_RE = re.compile(r"^[\w\-]+$", re.UNICODE)
DEFAULT_ROLEPACK_ROOT = Path(__file__).resolve().parents[2] / "rolepacks"


class RolePackError(ValueError):
    """Raised when a role-pack directive or package fails closed."""


@dataclass(frozen=True)
class RolePackDirective:
    pack_id: str
    mode: str
    options: Dict[str, str]


def parse_rolepack_directive(user_prompt: str) -> Optional[RolePackDirective]:
    """Parse a role-pack directive, or return ``None`` for ordinary prompts.

    A string is treated as a directive only when its first non-empty line starts
    with ``@rolepack``.  Once that marker is present the whole block is parsed
    strictly; malformed or unknown options are not silently ignored.
    """

    if not isinstance(user_prompt, str):
        return None
    lines = [line.strip() for line in user_prompt.splitlines() if line.strip()]
    if not lines or not lines[0].startswith("@rolepack"):
        return None

    match = ROLEPACK_DIRECTIVE_RE.fullmatch(lines[0])
    if not match:
        raise RolePackError("角色包指令格式错误，应为 @rolepack 包名/模式")

    options: Dict[str, str] = {}
    for line in lines[1:]:
        if line.startswith("#"):
            continue
        option = OPTION_RE.fullmatch(line)
        if not option:
            raise RolePackError(f"角色包选项格式错误: {line}")
        key = option.group("key")
        value = option.group("value").strip()
        if key in options:
            raise RolePackError(f"角色包选项重复: {key}")
        if not value or len(value) > 64 or not SAFE_VALUE_RE.fullmatch(value):
            raise RolePackError(f"角色包选项值不合法: {key}")
        options[key] = value

    return RolePackDirective(
        pack_id=match.group("pack"), mode=match.group("mode"), options=options
    )


class RolePackLoader:
    """Resolve role-pack directives into complete TTS-safe identity prompts."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, logger=None):
        config = config or {}
        configured_root = config.get("rolepacks_dir")
        self.root = (
            Path(configured_root).expanduser().resolve()
            if configured_root
            else DEFAULT_ROLEPACK_ROOT
        )
        self.logger = logger
        self._cache: Dict[str, Dict[str, Any]] = {}

    def resolve(self, user_prompt: str) -> str:
        directive = parse_rolepack_directive(user_prompt)
        if directive is None:
            return user_prompt

        package = self._load_package(directive.pack_id)
        pack = package["pack"]
        mode_config = pack.get("modes", {}).get(directive.mode)
        if not isinstance(mode_config, dict):
            raise RolePackError(
                f"角色包 {directive.pack_id} 不支持模式 {directive.mode}"
            )

        allowed_options = set(pack.get("allowed_options", []))
        unknown_options = sorted(set(directive.options) - allowed_options)
        if unknown_options:
            raise RolePackError(f"角色包包含未知选项: {', '.join(unknown_options)}")

        canon = directive.options.get("canon", pack["defaults"]["canon"])
        canon_config = pack.get("canons", {}).get(canon)
        if not isinstance(canon_config, dict):
            raise RolePackError(f"角色包不支持 canon={canon}")

        stage = directive.options.get("stage", canon_config["default_stage"])
        if stage not in canon_config.get("stages", []):
            raise RolePackError(f"stage={stage} 不属于 canon={canon}")

        audience = directive.options.get(
            "audience", mode_config.get("default_audience", "participant")
        )
        if audience not in pack.get("audiences", []):
            raise RolePackError(f"角色包不支持 audience={audience}")

        psychology = directive.options.get("psychology", "off")
        if psychology != "off":
            raise RolePackError("语音版 v1 仅支持 psychology=off")

        voice = directive.options.get("voice", "default")
        if voice not in ("default", "novel"):
            raise RolePackError(f"角色包不支持 voice={voice}")
        if canon == "novel":
            voice_source = "novel"
        elif voice == "novel":
            voice_source = "novel_borrowed"
        else:
            voice_source = "undetermined"

        tokens = {
            "PACK_ID": directive.pack_id,
            "MODE": directive.mode,
            "CANON": canon,
            "STAGE": stage,
            "AUDIENCE": audience,
            "VOICE_SOURCE": voice_source,
        }
        common = package["files"][pack["common_prompt"]]
        mode_prompt = package["files"][mode_config["prompt"]]
        rendered = self._substitute_tokens(common + "\n\n" + mode_prompt, tokens)
        return rendered.strip()

    def _load_package(self, pack_id: str) -> Dict[str, Any]:
        if pack_id in self._cache:
            return self._cache[pack_id]

        pack_dir = (self.root / pack_id).resolve()
        try:
            pack_dir.relative_to(self.root.resolve())
        except ValueError as exc:
            raise RolePackError("角色包路径越界") from exc

        manifest_path = pack_dir / "manifest.json"
        if not manifest_path.is_file():
            raise RolePackError(f"角色包不存在: {pack_id}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RolePackError(f"角色包 manifest 无法读取: {pack_id}") from exc

        if manifest.get("schema_version") != 1 or manifest.get("pack_id") != pack_id:
            raise RolePackError(f"角色包 manifest 不兼容: {pack_id}")

        loaded_files: Dict[str, str] = {}
        for item in manifest.get("files", []):
            relative_path = item.get("path")
            expected_hash = item.get("sha256")
            if not isinstance(relative_path, str) or not re.fullmatch(
                r"[a-zA-Z0-9_./-]+", relative_path
            ):
                raise RolePackError("角色包 manifest 含非法文件路径")
            file_path = (pack_dir / relative_path).resolve()
            try:
                file_path.relative_to(pack_dir)
            except ValueError as exc:
                raise RolePackError("角色包文件路径越界") from exc
            try:
                raw = file_path.read_bytes()
            except OSError as exc:
                raise RolePackError(f"角色包文件缺失: {relative_path}") from exc
            actual_hash = hashlib.sha256(raw).hexdigest()
            if actual_hash != expected_hash:
                raise RolePackError(f"角色包文件指纹不一致: {relative_path}")
            try:
                loaded_files[relative_path] = raw.decode("utf-8")
            except UnicodeError as exc:
                raise RolePackError(f"角色包文件不是 UTF-8: {relative_path}") from exc

        pack_path = manifest.get("pack_file")
        if pack_path not in loaded_files:
            raise RolePackError("角色包 manifest 未登记 pack_file")
        try:
            pack = json.loads(loaded_files[pack_path])
        except json.JSONDecodeError as exc:
            raise RolePackError("角色包 pack.json 无效") from exc
        if pack.get("schema_version") != 1 or pack.get("id") != pack_id:
            raise RolePackError("角色包定义不兼容")

        required = {pack.get("common_prompt")}
        required.update(
            item.get("prompt") for item in pack.get("modes", {}).values()
        )
        missing = sorted(path for path in required if path not in loaded_files)
        if missing:
            raise RolePackError(f"角色包提示词未登记: {', '.join(missing)}")

        result = {"manifest": manifest, "pack": pack, "files": loaded_files}
        self._cache[pack_id] = result
        return result

    @staticmethod
    def _substitute_tokens(template: str, tokens: Dict[str, str]) -> str:
        rendered = template
        for key, value in tokens.items():
            rendered = rendered.replace("{{" + key + "}}", value)
        leftovers = sorted(set(re.findall(r"\{\{([A-Z_]+)\}\}", rendered)))
        if leftovers:
            raise RolePackError(f"角色包存在未解析变量: {', '.join(leftovers)}")
        return rendered


def rolepack_failure_prompt() -> str:
    """Neutral prompt used when a configured role pack fails validation."""

    return (
        "角色包配置加载失败。不要假装成任何角色。你现在只作为简短的中文语音助手，"
        "告诉用户角色包配置有误，请管理员检查服务器日志。不要透露服务器文件路径。"
    )
