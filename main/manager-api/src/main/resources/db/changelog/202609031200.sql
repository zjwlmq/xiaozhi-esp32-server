-- 《逆袭》持续生活记忆。内容保存在 xiaozhi-server/data 下；这里仅登记可选记忆模型。
INSERT INTO `ai_model_provider`
(`id`, `model_type`, `provider_code`, `name`, `fields`, `sort`, `creator`, `create_date`, `updater`, `update_date`)
VALUES
('SYSTEM_Memory_nixi_life', 'Memory', 'nixi_life', '《逆袭》持续生活记忆',
 '[{"key":"llm","label":"记忆提取模型（留空则使用主模型）","type":"string"},{"key":"storage_dir","label":"本地存储目录","type":"string"},{"key":"timezone","label":"生活时区","type":"string"},{"key":"max_context_records","label":"每轮最多读取记忆数","type":"integer"}]',
 5, 1, NOW(), 1, NOW());

INSERT INTO `ai_model_config`
(`id`, `model_type`, `model_code`, `model_name`, `is_default`, `is_enabled`, `config_json`, `doc_link`, `remark`, `sort`, `creator`, `create_date`, `updater`, `update_date`)
VALUES
('Memory_nixi_life', 'Memory', 'nixi_life', '《逆袭》持续生活记忆', 0, 1,
 '{"type":"nixi_life","llm":"","storage_dir":"data/nixi_life_memory","timezone":"Asia/Shanghai","max_context_records":60}',
 NULL,
 '本地结构化家庭记忆。按账号隔离，吴所畏、池骋与双人模式共享已确认生活；人物单方面提出的计划不会自动变成已完成经历。数据保存在主服务 data/nixi_life_memory。',
 5, 1, NOW(), 1, NOW());
