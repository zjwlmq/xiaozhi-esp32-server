-- 火山引擎声音复刻上游手动同步：保存 OpenAPI AK/SK，并为每个音色记录
-- 实际使用的 seed-icl-1.0 / seed-icl-2.0，避免把 2.0 音色强制按 1.0 调用。
ALTER TABLE `ai_tts_voice`
  ADD COLUMN `upstream_resource_id` varchar(64) DEFAULT NULL COMMENT '上游复刻音色资源ID'
  AFTER `voice_demo`;

UPDATE `ai_model_provider`
SET `fields` = '[
  {"key": "ws_url", "type": "string", "label": "WebSocket地址"},
  {"key": "api_key", "type": "password", "label": "API Key（新版合成鉴权）"},
  {"key": "appid", "type": "string", "label": "应用ID（同步音色必填）"},
  {"key": "access_token", "type": "password", "label": "访问令牌（旧版合成兼容）"},
  {"key": "access_key_id", "type": "password", "label": "OpenAPI Access Key ID（同步音色）"},
  {"key": "access_key_secret", "type": "password", "label": "OpenAPI Access Key Secret（同步音色）"},
  {"key": "resource_id", "type": "string", "label": "资源ID"},
  {"key": "speaker", "type": "string", "label": "默认音色"},
  {"key": "enable_ws_reuse", "type": "boolean", "label": "是否开启链接复用", "default": true},
  {"key": "audio_params", "type": "dict", "label": "音频输出配置"},
  {"key": "additions", "type": "dict", "label": "高级文本处理配置"},
  {"key": "mix_speaker", "type": "dict", "label": "混音控制配置"}
]'
WHERE `id` IN ('SYSTEM_TTS_HSDSTTS', 'SYSTEM_TTS_HSDSTTS_V2');

UPDATE `ai_model_config`
SET `config_json` = JSON_SET(`config_json`, '$.access_key_id', '')
WHERE JSON_EXTRACT(`config_json`, '$.type') = 'huoshan_double_stream'
  AND JSON_EXTRACT(`config_json`, '$.access_key_id') IS NULL;

UPDATE `ai_model_config`
SET `config_json` = JSON_SET(`config_json`, '$.access_key_secret', '')
WHERE JSON_EXTRACT(`config_json`, '$.type') = 'huoshan_double_stream'
  AND JSON_EXTRACT(`config_json`, '$.access_key_secret') IS NULL;
