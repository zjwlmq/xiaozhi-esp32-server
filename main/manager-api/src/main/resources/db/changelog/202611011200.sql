CREATE TABLE IF NOT EXISTS ai_agent_extension_config (
    agent_id VARCHAR(32) NOT NULL,
    config_json LONGTEXT NOT NULL,
    runtime_status LONGTEXT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='智能体插件中心配置与最近运行状态';
