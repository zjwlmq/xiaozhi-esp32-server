"""Validated, connection-local controls for the hardwareless voice client."""

import copy
import math


DEFAULT_VOICE_SETTINGS = {
    "version": "server",
    "generation": "standard",
    "speed": 1.0,
    "pitch": 0,
    "language": "zh-cn",
}


def validate_voice_settings(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULT_VOICE_SETTINGS):
        raise ValueError("声音设置格式不正确")
    settings = {**DEFAULT_VOICE_SETTINGS, **value}
    if settings["version"] not in ("server", "1.0", "2.0"):
        raise ValueError("请选择声音复刻 1.0、2.0 或跟随智能体")
    if settings["generation"] not in ("standard", "restoration", "expressive", "trained"):
        raise ValueError("生成配置不受支持")
    if settings["version"] == "1.0" and settings["generation"] == "expressive":
        raise ValueError("表现力增强版仅适用于复刻 2.0")
    if settings["version"] == "2.0" and settings["generation"] not in ("standard", "expressive"):
        raise ValueError("复刻 2.0 支持标准版和表现力增强版；还原版需选择 1.0 并关联已训练音色")
    if settings["language"] not in ("auto", "zh-cn", "en"):
        raise ValueError("请选择自动、中英混读、中文或英文")
    speed = settings["speed"]
    if type(speed) not in (int, float) or not math.isfinite(speed) or not 0.5 <= speed <= 2:
        raise ValueError("语速必须在 0.5 到 2.0 倍之间")
    pitch = settings["pitch"]
    if type(pitch) is not int or not -12 <= pitch <= 12:
        raise ValueError("音调必须是 -12 到 12 之间的整数半音")
    return settings


def get_voice_variants(config, voice):
    variants = config.get("browser_voice_variants")
    entry = variants.get(voice) if isinstance(variants, dict) else None
    return entry if isinstance(entry, dict) else {}


def configure_voice_settings(conn, value=None):
    """Never accept provider credentials, URLs or arbitrary voice IDs from a client."""
    selected = conn.config.get("selected_module", {}).get("TTS")
    config = conn.config.get("TTS", {}).get(selected, {})
    voice = config.get("private_voice") or config.get("speaker") or ""
    supported = (not conn.need_bind and config.get("type") == "huoshan_double_stream"
                 and isinstance(voice, str) and voice.startswith("S_"))
    result = {"supported": supported, "voice": voice if supported else ""}
    try:
        settings = validate_voice_settings(value if value is not None else DEFAULT_VOICE_SETTINGS)
        if settings["version"] != "server" and not supported:
            raise ValueError("请先在智控台为当前智能体选择火山双流式模型和复刻音色")
        if settings["version"] != "server":
            parameters = build_voice_parameters({
                "resource_id": config.get("resource_id"), "speaker": voice,
                "variants": get_voice_variants(config, voice),
                "audio_params": {}, "additions": {},
            }, settings)
            result["voice"] = parameters["speaker"]
        # Assignment is atomic. The provider snapshots this at the next utterance.
        conn.browser_tts_settings = settings if settings["version"] != "server" else None
        result.update(status="accepted", settings=settings, applies_to="next_utterance")
    except ValueError as error:
        result.update(status="error", message=str(error))
    return result


def build_voice_parameters(defaults, settings):
    """Use only the bound voice or its server-configured, already trained variants."""
    parameters = copy.deepcopy(defaults)
    if not settings or settings["version"] == "server":
        return parameters
    settings = validate_voice_settings(settings)
    resource = "seed-icl-" + settings["version"]
    # Keep an existing 1.0 concurrency subscription when selecting 1.0.
    parameters["resource_id"] = (defaults["resource_id"] if
        defaults.get("resource_id") == resource + "-concurr" else resource)
    parameters["model"] = None
    if settings["version"] == "2.0":
        parameters["model"] = ("seed-tts-2.0-standard" if settings["generation"] == "standard"
                               else "seed-tts-2.0-expressive")
    elif settings["generation"] != "trained":
        speaker = defaults.get("variants", {}).get(settings["generation"])
        if not isinstance(speaker, str) or not speaker.strip() or len(speaker) > 256:
            label = "标准版" if settings["generation"] == "standard" else "还原版"
            raise ValueError(f"当前音色尚未关联 1.0 {label}训练音色，请在服务端配置后使用；也可选择跟随音色训练")
        parameters["speaker"] = speaker.strip()
    parameters["audio_params"]["speech_rate"] = round((settings["speed"] - 1) * 100)
    additions = parameters["additions"]
    additions.setdefault("post_process", {})["pitch"] = settings["pitch"]
    if settings["language"] == "auto":
        additions.pop("explicit_language", None)
    else:
        additions["explicit_language"] = settings["language"]
    return parameters
