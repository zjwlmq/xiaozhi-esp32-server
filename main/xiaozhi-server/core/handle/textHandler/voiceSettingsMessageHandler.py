import json

from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from core.utils.voice_settings import configure_voice_settings


class VoiceSettingsMessageHandler(TextMessageHandler):
    @property
    def message_type(self):
        return TextMessageType.VOICE_SETTINGS

    async def handle(self, conn, msg_json):
        result = configure_voice_settings(conn, msg_json.get("settings"))
        request_id = msg_json.get("request_id")
        await conn.websocket.send(json.dumps({
            "type": "voice_settings",
            "request_id": request_id if isinstance(request_id, str) and len(request_id) <= 64 else None,
            **result,
        }, ensure_ascii=False))
