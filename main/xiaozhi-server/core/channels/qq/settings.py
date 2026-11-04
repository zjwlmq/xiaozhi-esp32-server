"""Operator-owned QQ settings. Incoming events cannot select devices or models."""
import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


def qq_id(value):
    value = str(value)
    if not re.fullmatch(r"[1-9][0-9]{4,19}", value):
        raise ValueError("QQ ID must be a positive numeric ID")
    return value


def endpoint(value, schemes):
    parsed = urlsplit(value)
    if (parsed.scheme not in schemes or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Invalid OneBot endpoint; put credentials in access_token")
    return value.rstrip("/")


@dataclass(frozen=True)
class Route:
    id: str
    kind: str
    peer_id: str
    device_id: str
    reply_mode: str = "text"
    require_at: bool = True
    members: tuple = ()


@dataclass
class Settings:
    self_id: str
    api_key: str
    http_url: str
    access_token: str = ""
    websocket_url: str = ""
    webhook_secret: str = ""
    media_allowed_origins: tuple = ()
    routes: dict = field(default_factory=dict)
    state_path: str = "data/qq-bridge/events.sqlite3"
    turn_timeout: int = 180
    max_event_age: int = 300
    # None preserves the original shared-token behaviour; "" means unauthenticated WS.
    websocket_access_token: str | None = field(default=None, repr=False)

    @classmethod
    def parse(cls, raw):
        if not isinstance(raw, dict) or raw.get("enabled") is not True:
            return None
        self_id = qq_id(raw.get("self_id", ""))
        key = raw.get("api_key", "")
        if not isinstance(key, str) or len(key) < 32 or key.startswith("CHANGE_ME"):
            raise ValueError("qq_bridge.api_key needs a random secret of at least 32 characters")
        secret = raw.get("webhook_secret", "")
        if secret and (not isinstance(secret, str) or len(secret) < 32):
            raise ValueError("qq_bridge.webhook_secret needs at least 32 characters")
        routes, peers = {}, set()
        for item in raw.get("routes", []):
            name = item.get("id", "")
            kind = item.get("kind", "private")
            peer = qq_id(item.get("peer_id", ""))
            mode = item.get("reply_mode", "text")
            if (not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", name) or name in routes
                    or kind not in ("private", "group") or mode not in ("text", "voice", "both")
                    or (kind, peer) in peers or peer == self_id):
                raise ValueError("Invalid or duplicate QQ route")
            # A stable, locally administered unicast MAC accepted by the existing OTA API.
            digest = hashlib.sha256(f"qq:{self_id}:{kind}:{peer}".encode()).digest()
            device = ":".join(f"{x:02x}" for x in b"\x02" + digest[:5])
            routes[name] = Route(name, kind, peer, device, mode,
                                 item.get("require_at", True) is not False,
                                 tuple(qq_id(x) for x in item.get("members", [])))
            peers.add((kind, peer))
        if not 1 <= len(routes) <= 64:
            raise ValueError("Configure between 1 and 64 explicit QQ routes")
        ws = raw.get("websocket_url", "")
        http_token = raw.get("access_token", "")
        if not isinstance(http_token, str) or '\r' in http_token or '\n' in http_token:
            raise ValueError("qq_bridge.access_token must be a single-line string")
        ws_token = raw.get("websocket_access_token")
        if ws_token is not None and (not isinstance(ws_token, str) or '\r' in ws_token or '\n' in ws_token):
            raise ValueError("qq_bridge.websocket_access_token must be a single-line string or null")
        origins = tuple(endpoint(x, ("https", "http")) for x in raw.get("media_allowed_origins", []))
        if any(urlsplit(x).path not in ("", "/") for x in origins):
            raise ValueError("media_allowed_origins must contain exact origins, without paths")
        return cls(self_id, key, endpoint(raw.get("http_url", ""), ("http", "https")),
                   http_token, endpoint(ws, ("ws", "wss")) if ws else "",
                   secret, origins, routes, str(raw.get("state_path", "data/qq-bridge/events.sqlite3")),
                   max(30, min(600, int(raw.get("turn_timeout", 180)))),
                   max(30, min(600, int(raw.get("max_event_age", 300)))),
                   websocket_access_token=ws_token)
