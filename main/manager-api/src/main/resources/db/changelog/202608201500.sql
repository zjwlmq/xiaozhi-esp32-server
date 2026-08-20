INSERT INTO `sys_params`
    (`id`, `param_code`, `param_value`, `value_type`, `param_type`, `remark`)
VALUES
    (503, 'nixi.rolepack.access_policy', '{"mode":"owner","whitelistUserIds":[]}', 'json', 1,
     '《逆袭》角色包访问策略：owner 仅站长、whitelist 白名单、public 全站公开')
ON DUPLICATE KEY UPDATE `param_code` = VALUES(`param_code`);
