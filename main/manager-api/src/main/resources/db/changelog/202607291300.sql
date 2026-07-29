DELETE FROM `ai_model_provider`
WHERE `id` = 'SYSTEM_LLM_anthropic_messages';

INSERT INTO `ai_model_provider`
    (`id`, `model_type`, `provider_code`, `name`, `fields`, `sort`, `creator`, `create_date`, `updater`, `update_date`)
VALUES
    (
        'SYSTEM_LLM_anthropic_messages',
        'LLM',
        'anthropic_messages',
        'Anthropic Messages（原生）',
        '[
          {"key":"base_url","label":"基础URL（根地址、/v1 或 /v1/messages）","type":"string"},
          {"key":"model_name","label":"模型名称","type":"string"},
          {"key":"api_key","label":"API密钥","type":"password"},
          {"key":"auth_type","label":"认证方式（x-api-key / bearer）","type":"string"},
          {"key":"anthropic_version","label":"Anthropic版本","type":"string"},
          {"key":"user_agent","label":"User-Agent","type":"string"},
          {"key":"max_tokens","label":"最大令牌数","type":"number"},
          {"key":"temperature","label":"温度","type":"number"},
          {"key":"top_p","label":"top_p值","type":"number"},
          {"key":"timeout","label":"超时时间（秒）","type":"number"}
        ]',
        11,
        1,
        NOW(),
        1,
        NOW()
    );
