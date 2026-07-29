-- Keep the Anthropic Messages form aligned with the compact two-column layout
-- used by the original OpenAI provider. Detailed guidance belongs in input
-- placeholders so long labels do not squeeze every input in the form.
UPDATE `ai_model_provider`
SET `fields` = '[
  {"key":"base_url","label":"基础URL","type":"string","placeholder":"支持根地址、/v1 或 /v1/messages"},
  {"key":"model_name","label":"模型名称","type":"string","placeholder":"请输入实际请求模型名称"},
  {"key":"api_key","label":"API密钥","type":"password","placeholder":"请输入API密钥"},
  {"key":"auth_type","label":"认证方式","type":"string","default":"x-api-key","placeholder":"请选择认证方式","options":[{"label":"x-api-key","value":"x-api-key"},{"label":"Bearer","value":"bearer"}]},
  {"key":"anthropic_version","label":"协议版本","type":"string","default":"2023-06-01","placeholder":"例如 2023-06-01"},
  {"key":"user_agent","label":"User-Agent","type":"string","placeholder":"按需填写，例如 curl/8.5.0"},
  {"key":"max_tokens","label":"最大令牌数","type":"number","default":1024,"placeholder":"例如 1024"},
  {"key":"temperature","label":"温度","type":"number","default":0.7,"placeholder":"例如 0.7"},
  {"key":"top_p","label":"top_p值","type":"number","default":1,"placeholder":"例如 1"},
  {"key":"timeout","label":"超时（秒）","type":"number","default":300,"placeholder":"例如 300"}
]',
    `update_date` = NOW()
WHERE `id` = 'SYSTEM_LLM_anthropic_messages';
