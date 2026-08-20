"""Load compact, deployment-safe role packs from a short system-prompt directive.

The manager UI only needs to store a directive such as::

    @rolepack nixi/wu
    canon=novel
    stage=S7

Role-pack files are shipped with xiaozhi-server.  The original authoring Skill is
therefore not required inside a Docker container or on the production host.
"""

from __future__ import annotations

import base64
import binascii
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
DAUGHTER_PROFILE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
DEFAULT_ROLEPACK_ROOT = Path(__file__).resolve().parents[2] / "rolepacks"

DAUGHTER_PROFILE_DEFAULTS = {
    "schema_version": 1,
    "name": "女儿",
    "age_stage": "adult",
    "origin": "unspecified",
    "calls_wu": "吴爸",
    "calls_chi": "池爸",
    "wu_calls": "闺女",
    "chi_calls": "丫头",
    "wu_style": "嘴上会算账和追问细节，实际会照顾，但尊重女儿自己做决定",
    "chi_style": "话少，优先处理问题和提供保护，但不能替女儿决定未说明的想法",
    "family_rules": "两人发生分歧时不把女儿当裁判，不用原著关系压过女儿当下明确表达的边界",
}
DAUGHTER_TEXT_LIMITS = {
    "name": 24,
    "calls_wu": 24,
    "calls_chi": 24,
    "wu_calls": 24,
    "chi_calls": 24,
    "wu_style": 120,
    "chi_style": 120,
    "family_rules": 240,
}
DAUGHTER_AGE_STAGES = {"child", "teen", "adult"}
DAUGHTER_ORIGINS = {"unspecified", "adopted", "co_parented"}


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
        is_daughter_profile = key == "daughter_profile"
        max_length = 4096 if is_daughter_profile else 64
        value_pattern = DAUGHTER_PROFILE_RE if is_daughter_profile else SAFE_VALUE_RE
        if not value or len(value) > max_length or not value_pattern.fullmatch(value):
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

        daughter_profile_value = directive.options.get("daughter_profile")
        if daughter_profile_value and audience != "daughter":
            raise RolePackError("daughter_profile 仅可与 audience=daughter 同时使用")
        daughter_profile = self._load_daughter_profile(daughter_profile_value)

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
            "AUDIENCE_CONTEXT": self._render_audience_context(
                audience, directive.mode, daughter_profile
            ),
        }
        common = package["files"][pack["common_prompt"]]
        mode_prompt = package["files"][mode_config["prompt"]]
        rendered = self._substitute_tokens(common + "\n\n" + mode_prompt, tokens)
        return rendered.strip()

    @staticmethod
    def _load_daughter_profile(encoded: Optional[str]) -> Dict[str, Any]:
        if not encoded:
            return dict(DAUGHTER_PROFILE_DEFAULTS)
        try:
            padded = encoded + "=" * ((4 - len(encoded) % 4) % 4)
            raw = base64.urlsafe_b64decode(padded.encode("ascii"))
            decoded = json.loads(raw.decode("utf-8"))
        except (
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
            binascii.Error,
        ) as exc:
            raise RolePackError("daughter_profile 无法解析") from exc
        if not isinstance(decoded, dict) or decoded.get("schema_version") != 1:
            raise RolePackError("daughter_profile 版本不兼容")
        unknown = sorted(set(decoded) - set(DAUGHTER_PROFILE_DEFAULTS))
        if unknown:
            raise RolePackError(f"daughter_profile 包含未知字段: {', '.join(unknown)}")

        profile = dict(DAUGHTER_PROFILE_DEFAULTS)
        for key, limit in DAUGHTER_TEXT_LIMITS.items():
            value = decoded.get(key, profile[key])
            if not isinstance(value, str):
                raise RolePackError(f"daughter_profile 字段类型错误: {key}")
            value = value.strip()
            if (
                not value
                or len(value) > limit
                or re.search(r"[\r\n{}<>\x00-\x1f\x7f]", value)
            ):
                raise RolePackError(f"daughter_profile 字段值不合法: {key}")
            profile[key] = value
        age_stage = decoded.get("age_stage", profile["age_stage"])
        origin = decoded.get("origin", profile["origin"])
        if age_stage not in DAUGHTER_AGE_STAGES:
            raise RolePackError("daughter_profile 年龄阶段不合法")
        if origin not in DAUGHTER_ORIGINS:
            raise RolePackError("daughter_profile 家庭来源不合法")
        profile["age_stage"] = age_stage
        profile["origin"] = origin
        return profile

    @staticmethod
    def _render_audience_context(
        audience: str, mode: str, profile: Dict[str, Any]
    ) -> str:
        if audience == "participant":
            return (
                "五、交互身份。用户是无固定原作身份的当前谈话者，可以被人物直接回应，"
                "但不得擅自认定用户就是某个原作人物。"
            )
        if audience == "observer":
            return (
                "五、交互身份。用户只负责给场景和推动情节，人物不向用户索要场内回应。"
            )

        age_labels = {"child": "儿童", "teen": "青少年", "adult": "成年"}
        origin_labels = {
            "unspecified": "家庭来源不说明",
            "adopted": "由两人共同收养",
            "co_parented": "由两人共同抚养",
        }
        mode_guidance = {
            "wu": "当前只有吴所畏出声；池骋仍是家庭成员，但不得替池骋说话或代写其心理。",
            "chi": "当前只有池骋出声；吴所畏仍是家庭成员，但不得替吴所畏说话或代写其心理。",
            "duo": "两人都可以直接回应女儿，但仍遵守双人声道、私有心理隔离和不强求等量发言。",
        }[mode]
        return (
            "五、交互身份与女儿设定。用户是吴所畏与池骋共同的女儿，姓名或昵称为“"
            f"{profile['name']}”，年龄阶段为{age_labels[profile['age_stage']]}，"
            f"{origin_labels[profile['origin']]}。女儿称吴所畏“{profile['calls_wu']}”，"
            f"女儿称池骋“{profile['calls_chi']}”；吴所畏称女儿“{profile['wu_calls']}”，"
            f"池骋称女儿“{profile['chi_calls']}”。吴所畏与女儿的相处方式："
            f"{profile['wu_style']}。池骋与女儿的相处方式：{profile['chi_style']}。"
            f"家庭互动规则：{profile['family_rules']}。{mode_guidance}"
            "女儿及其家庭经历属于本次角色配置的 session fiction，不是小说或剧版 canon；"
            "可编辑设定只调整家庭互动方式，不能覆盖人物核心、事实分层或安全边界。"
            "亲子关系始终是非浪漫、非性化的家庭关系。不得伪造原著出处，也不得凭空"
            "决定女儿没有表达的经历、感受或意愿。"
        )

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
