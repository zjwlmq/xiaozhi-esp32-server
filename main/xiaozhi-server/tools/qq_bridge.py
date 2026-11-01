"""Configure and inspect the QQ channel without exposing tokens or sending QQ messages."""
import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path
import secrets
import sys

import aiohttp
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.channels.qq.settings import Settings
from core.channels.qq.onebot import OneBot, OneBotError


def write_new_config(path, raw):
    settings = Settings.parse(raw)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite existing credentials, routes or operator settings.
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        yaml.safe_dump({"qq_bridge": raw}, stream, allow_unicode=True, sort_keys=False)
    return settings


async def run(args):
    path = Path(args.config)
    if args.command == "init":
        if path.exists():
            raise ValueError("配置已存在，未覆盖。请编辑 data/.qq-bridge.yaml 后重启小智服务。")
        token = os.environ.get(args.access_token_env, "") if args.access_token_env else getpass.getpass("OneBot Access Token（输入不回显，可留空）：")
        if args.access_token_env and args.access_token_env not in os.environ:
            raise ValueError("指定的 OneBot token 环境变量不存在")
        raw = {"enabled": True, "self_id": args.self_id, "api_key": secrets.token_urlsafe(32),
               "webhook_secret": secrets.token_urlsafe(32), "http_url": args.http_url,
               "websocket_url": args.ws_url, "access_token": token, "media_allowed_origins": [],
               "routes": [{"id": "friend", "kind": "private", "peer_id": args.peer_id, "reply_mode": "text"}]}
        settings = write_new_config(path, raw)
        print("已保存私有配置：" + str(path))
        print("QQ 会话的设备编号：" + settings.routes["friend"].device_id)
        print("重启小智 Python 服务后运行 status 和 prepare --route friend。未发送 QQ 消息。")
        return
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    settings = Settings.parse(raw.get("qq_bridge", {}))
    if settings is None:
        raise ValueError("QQ 渠道尚未启用：请检查 enabled: true")
    if args.command == "check":
        client = OneBot(settings)
        await client.start()
        try:
            await client.verify_account()
            print("OneBot HTTP 连接正常，登录 QQ 与 self_id 匹配。未发送 QQ 消息。")
        finally:
            await client.close()
        return
    route = "/status" if args.command == "status" else "/bindings/" + args.route + "/prepare"
    method = "GET" if args.command == "status" else "POST"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25), trust_env=False) as http:
        async with http.request(method, args.base_url.rstrip("/") + "/xiaozhi/qq" + route,
                                headers={"Authorization": "Bearer " + settings.api_key}, allow_redirects=False) as response:
            if response.status != 200:
                raise ValueError("QQ 接口返回 HTTP " + str(response.status) + "；确认代码已更新、配置已启用并已重启服务")
            print(json.dumps(await response.json(), ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="data/.qq-bridge.yaml")
    parser.add_argument("--base-url", default="http://127.0.0.1:8003")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="生成配置和随机密钥；不覆盖已有文件")
    init.add_argument("--self-id", required=True, help="机器人登录的 QQ 号")
    init.add_argument("--peer-id", required=True, help="允许私聊的测试 QQ 号")
    init.add_argument("--http-url", required=True, help="小智容器可访问的 OneBot HTTP API")
    init.add_argument("--ws-url", default="", help="OneBot 正向 WebSocket URL")
    init.add_argument("--access-token-env", help="从指定环境变量取 OneBot token；默认交互输入")
    commands.add_parser("status", help="查看小智 QQ 路由状态")
    commands.add_parser("check", help="只读检查 OneBot HTTP 和登录账号")
    commands.add_parser("prepare", help="生成/查询智控台设备激活码；不向 QQ 发送").add_argument("--route", default="friend")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (ValueError, OSError, RuntimeError, aiohttp.ClientError, asyncio.TimeoutError) as error:
        print(str(error) if isinstance(error, (ValueError, OneBotError)) else "操作失败：" + type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
