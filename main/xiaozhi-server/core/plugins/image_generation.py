"""OpenAI-compatible image generation; only invoked by an enabled runtime tool."""
import base64
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


async def resolve_endpoint(endpoint, allowed_origins=()):
    """Pin the validated address so DNS cannot redirect a request into the LAN."""
    import httpx
    parsed = urlsplit(endpoint)
    if (parsed.scheme not in ('https', 'http') or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('生图接口地址无效')
    url = httpx.URL(endpoint)
    origin = str(url.copy_with(path='/', query=None, fragment=None)).rstrip('/')
    allowed = origin in {str(value).rstrip('/') for value in allowed_origins}
    if url.scheme != 'https' and not allowed:
        raise ValueError('生图接口需要 HTTPS')
    hostname = url.raw_host.decode('ascii')
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        entries = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
            hostname, url.port or (443 if url.scheme == 'https' else 80), type=socket.SOCK_STREAM), timeout=5)
        addresses = [ipaddress.ip_address(entry[4][0]) for entry in entries]
    if not addresses or (not allowed and any(
            not address.is_global or address.is_multicast or address.is_reserved for address in addresses)):
        raise ValueError('内网生图服务需要由管理员设置允许的服务地址')
    # Prefer IPv4 where available; TLS still verifies the original hostname.
    address = min(addresses, key=lambda value: value.version)
    return url.copy_with(host=str(address)), url.netloc.decode('ascii'), hostname


async def generate_image(settings, prompt, client=None, allowed_origins=()):
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
        raise ValueError('图片描述应为1至4000字')
    import httpx
    target, host, server_name = await resolve_endpoint(settings['endpoint'], allowed_origins)
    owned = client is None
    client = client or httpx.AsyncClient(timeout=120, follow_redirects=False, trust_env=False)
    try:
        async with client.stream('POST', target,
                headers={'Host': host, 'Authorization': 'Bearer ' + settings['api_key']},
                extensions={'sni_hostname': server_name},
                json={'model': settings['model'], 'prompt': prompt.strip(), 'n': 1, 'size': settings['size']}) as response:
            response.raise_for_status()
            chunks, total = [], 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > 16 * 1024 * 1024: raise ValueError('生图响应超过大小限制')
                chunks.append(chunk)
        import json
        data = json.loads(b''.join(chunks))
        item = data.get('data', [])[0]
        if item.get('b64_json'):
            encoded = item['b64_json']
            raw = base64.b64decode(encoded, validate=True)
            if raw.startswith(b'\x89PNG\r\n\x1a\n'): mime = 'image/png'
            elif raw.startswith(b'\xff\xd8\xff'): mime = 'image/jpeg'
            elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP': mime = 'image/webp'
            else: raise ValueError('生图结果不是支持的图片格式')
            return {'url': f'data:{mime};base64,{encoded}', 'mime_type': mime}
        url = item.get('url', '')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('生图服务未返回有效图片')
        return {'url': url}
    finally:
        if owned: await client.aclose()
