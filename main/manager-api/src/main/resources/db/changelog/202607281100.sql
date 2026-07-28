-- 火山引擎双向流式 TTS 支持新版 API Key 鉴权，同时保留旧版鉴权字段。
UPDATE `ai_model_provider`
SET `fields` = '[
  {"key": "ws_url", "type": "string", "label": "WebSocket地址"},
  {"key": "api_key", "type": "password", "label": "API Key（新版鉴权，推荐）"},
  {"key": "appid", "type": "string", "label": "应用ID（旧版兼容）"},
  {"key": "access_token", "type": "string", "label": "访问令牌（旧版兼容）"},
  {"key": "resource_id", "type": "string", "label": "资源ID"},
  {"key": "speaker", "type": "string", "label": "默认音色"},
  {"key": "enable_ws_reuse", "type": "boolean", "label": "是否开启链接复用", "default": true},
  {"key": "audio_params", "type": "dict", "label": "音频输出配置"},
  {"key": "additions", "type": "dict", "label": "高级文本处理配置"},
  {"key": "mix_speaker", "type": "dict", "label": "混音控制配置"}
]'
WHERE `id` = 'SYSTEM_TTS_HSDSTTS';

-- 只给尚未包含 api_key 的配置添加空字段，不覆盖用户已有密钥。
UPDATE `ai_model_config`
SET `config_json` = JSON_SET(`config_json`, '$.api_key', '')
WHERE `id` IN ('TTS_HuoshanDoubleStreamTTS', 'TTS_HSDSTTS_V2')
  AND JSON_EXTRACT(`config_json`, '$.api_key') IS NULL;

UPDATE `ai_model_config`
SET
  `doc_link` = 'https://docs.volcengine.com/docs/6561/1329505?lang=zh',
  `remark` = '火山引擎双向流式TTS配置说明：
1. 新版控制台（推荐）：在“快速接入”页面获取 API Key，只填写“API Key（新版鉴权，推荐）”即可；应用ID和访问令牌可留空。
2. 旧版控制台：API Key留空，继续填写应用ID和访问令牌。
3. WebSocket地址：wss://openspeech.bytedance.com/api/v3/tts/bidirection
4. 湾湾小何 1.0：资源ID填 seed-tts-1.0，默认音色填 zh_female_wanwanxiaohe_moon_bigtts。
5. 小何 2.0：资源ID填 seed-tts-2.0，默认音色填 zh_female_xiaohe_uranus_bigtts。
6. 如果购买的是并发版 1.0，资源ID可按控制台权益填写 seed-tts-1.0-concurr。

安全提示：API Key属于敏感凭证，请勿截图或公开分享。'
WHERE `id` IN ('TTS_HuoshanDoubleStreamTTS', 'TTS_HSDSTTS_V2');
