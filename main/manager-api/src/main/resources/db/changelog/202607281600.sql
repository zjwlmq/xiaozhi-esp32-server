-- 在音色列表中明确区分 1.0 与 2.0，避免两个版本都显示为“湾湾小何”。
-- 2.0 与 1.0 共用 provider_code=huoshan_double_stream 的供应器表单，
-- API Key 字段已由 202607281100 变更集统一补充。
UPDATE `ai_tts_voice`
SET `name` = '小何2.0'
WHERE `tts_model_id` = 'TTS_HSDSTTS_V2'
  AND `tts_voice` = 'zh_female_xiaohe_uranus_bigtts';
