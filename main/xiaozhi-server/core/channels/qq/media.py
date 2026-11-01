"""Bounded media downloads with DNS pinning, and file ASR conversion."""
import asyncio
import base64
import tempfile
from pathlib import Path

import httpx

from core.plugins.image_generation import resolve_endpoint

MAX_MEDIA = 5 * 1024 * 1024


def image_bytes(raw):
    if not (raw.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a"))
            or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")):
        raise ValueError("Unsupported image format")
    return raw


async def download(source, allowed_origins=()):
    if not isinstance(source, str) or not source:
        raise ValueError("Media URL is missing")
    if source.startswith(("base64://", "data:")):
        if source.startswith("data:"):
            head, _, encoded = source.partition(",")
            if not head.endswith(";base64"):
                raise ValueError("Invalid data URL")
        else:
            encoded = source[9:]
        if len(encoded) > (MAX_MEDIA + 2) // 3 * 4:
            raise ValueError("Media exceeds 5 MiB")
        raw = base64.b64decode(encoded, validate=True)
    else:
        original = httpx.URL(source)
        if original.fragment:
            raise ValueError("Media URL fragments are not supported")
        # Validate origin and pin DNS before restoring signed CDN query parameters.
        target, host, name = await resolve_endpoint(str(original.copy_with(query=None)), allowed_origins)
        target = target.copy_with(query=original.query)
        async with httpx.AsyncClient(timeout=25, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", target, headers={"Host": host},
                                     extensions={"sni_hostname": name}) as response:
                if response.status_code != 200:
                    raise ValueError("Media download failed")
                chunks, total = [], 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_MEDIA:
                        raise ValueError("Media exceeds 5 MiB")
                    chunks.append(chunk)
                raw = b"".join(chunks)
    if not raw or len(raw) > MAX_MEDIA:
        raise ValueError("Media is empty or exceeds 5 MiB")
    return raw


async def pcm_audio(raw):
    """No shell, network protocols or caller-provided paths are passed to ffmpeg."""
    with tempfile.TemporaryDirectory(prefix="xiaozhi-qq-") as directory:
        output = Path(directory) / "output.pcm"
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-protocol_whitelist", "pipe", "-i", "pipe:0", "-t", "91",
            "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", str(output),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            await asyncio.wait_for(process.communicate(raw), 30)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        if process.returncode != 0 or not output.exists():
            raise ValueError("Audio conversion failed; configure OneBot get_record to return WAV/MP3")
        if output.stat().st_size > 90 * 16000 * 2:
            raise ValueError("Voice message exceeds 90 seconds")
        pcm = output.read_bytes()
        if not pcm:
            raise ValueError("Empty voice message")
        return [pcm[i:i + 1920] for i in range(0, len(pcm), 1920)]


async def outbound_segments(message, origins=()):
    if isinstance(message, str):
        message = [{"type": "text", "data": {"text": message}}]
    if not isinstance(message, list) or not 1 <= len(message) <= 8:
        raise ValueError("message must contain 1 to 8 segments")
    result = []
    for part in message:
        kind, data = part.get("type"), part.get("data", {})
        if kind == "text":
            value = data.get("text")
            if not isinstance(value, str) or not 1 <= len(value) <= 4000:
                raise ValueError("Invalid message text")
            result.append({"type": kind, "data": {"text": value}})
        elif kind == "face":
            value = str(data.get("id", ""))
            if not value.isdecimal() or len(value) > 5:
                raise ValueError("Invalid QQ face ID")
            result.append({"type": kind, "data": {"id": value}})
        elif kind in ("image", "record"):
            raw = await download(data.get("url") or data.get("file"), origins)
            if kind == "image":
                image_bytes(raw)
            result.append({"type": kind, "data": {"file": "base64://" + base64.b64encode(raw).decode()}})
        else:
            raise ValueError("Only text, image, face and record can be sent")
    return result
