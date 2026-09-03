package xiaozhi.modules.agent.service;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;

import lombok.AllArgsConstructor;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.utils.JsonUtils;
import xiaozhi.modules.agent.dto.NixiRolepackAccessPolicyDTO;
import xiaozhi.modules.agent.vo.NixiRolepackAccessPolicyVO;
import xiaozhi.modules.sys.dao.SysUserDao;
import xiaozhi.modules.sys.entity.SysUserEntity;
import xiaozhi.modules.sys.enums.SuperAdminEnum;
import xiaozhi.modules.sys.service.SysParamsService;

@Service
@AllArgsConstructor
public class NixiRolepackAccessService {
    public static final String PARAM_CODE = "nixi.rolepack.access_policy";
    public static final String MODE_OWNER = "owner";
    public static final String MODE_WHITELIST = "whitelist";
    public static final String MODE_PUBLIC = "public";
    public static final String DENIED_PROMPT = "当前智能体使用的《逆袭》角色包未获得授权，请联系站点管理员。";

    private static final Set<String> ALLOWED_MODES = Set.of(MODE_OWNER, MODE_WHITELIST, MODE_PUBLIC);
    private static final Pattern NIXI_DIRECTIVE = Pattern.compile(
            "^@rolepack\\s+nixi/(wu|chi|duo)(?:\\s|$)");

    private final SysParamsService sysParamsService;
    private final SysUserDao sysUserDao;

    public boolean isNixiPrompt(String prompt) {
        if (prompt == null) {
            return false;
        }
        return prompt.lines()
                .map(String::trim)
                .filter(StringUtils::isNotBlank)
                .findFirst()
                .map(line -> NIXI_DIRECTIVE.matcher(line).find())
                .orElse(false);
    }

    public String getNixiMode(String prompt) {
        if (prompt == null) {
            return null;
        }
        return prompt.lines()
                .map(String::trim)
                .filter(StringUtils::isNotBlank)
                .findFirst()
                .map(line -> {
                    Matcher matcher = NIXI_DIRECTIVE.matcher(line);
                    return matcher.find() ? matcher.group(1) : null;
                })
                .orElse(null);
    }

    public boolean isAllowed(Long userId) {
        if (userId == null) {
            return false;
        }
        SysUserEntity user = sysUserDao.selectById(userId);
        if (user == null || !Integer.valueOf(1).equals(user.getStatus())) {
            return false;
        }
        if (isSuperAdmin(user)) {
            return true;
        }

        NixiRolepackAccessPolicyDTO policy = loadPolicy();
        if (MODE_PUBLIC.equals(policy.getMode())) {
            return true;
        }
        return MODE_WHITELIST.equals(policy.getMode())
                && policy.getWhitelistUserIds().contains(userId);
    }

    public void assertPromptAllowed(Long userId, String prompt) {
        if (isNixiPrompt(prompt) && !isAllowed(userId)) {
            throw new RenException("当前账号没有使用《逆袭》角色包的权限，请联系站点管理员");
        }
    }

    public String enforceRuntimePrompt(Long userId, String prompt) {
        if (isNixiPrompt(prompt) && !isAllowed(userId)) {
            return DENIED_PROMPT;
        }
        return prompt;
    }

    public NixiRolepackAccessPolicyVO getPolicyView(Long currentUserId) {
        NixiRolepackAccessPolicyDTO policy = loadPolicy();
        SysUserEntity currentUser = sysUserDao.selectById(currentUserId);
        boolean editable = isSuperAdmin(currentUser);

        NixiRolepackAccessPolicyVO view = new NixiRolepackAccessPolicyVO();
        view.setMode(policy.getMode());
        view.setCurrentUserAllowed(isAllowed(currentUserId));
        view.setEditable(editable);
        if (editable) {
            view.setWhitelistUserIds(new ArrayList<>(policy.getWhitelistUserIds()));
            List<SysUserEntity> users = sysUserDao.selectList(
                    new QueryWrapper<SysUserEntity>().orderByAsc("id"));
            view.setUsers(users.stream().map(this::toUserOption).collect(Collectors.toList()));
        }
        return view;
    }

    @Transactional(rollbackFor = Exception.class)
    public NixiRolepackAccessPolicyVO savePolicy(Long currentUserId, NixiRolepackAccessPolicyDTO requested) {
        NixiRolepackAccessPolicyDTO normalized = normalizePolicy(requested);
        String json = JsonUtils.toJsonString(normalized);
        if (StringUtils.isBlank(sysParamsService.getValue(PARAM_CODE, false))) {
            throw new RenException("《逆袭》角色包访问策略参数不存在，请确认数据库迁移已完成");
        }
        sysParamsService.updateValueByCode(PARAM_CODE, json);
        if (!StringUtils.equals(json, sysParamsService.getValue(PARAM_CODE, false))) {
            throw new RenException("《逆袭》角色包访问策略保存失败");
        }
        return getPolicyView(currentUserId);
    }

    public NixiRolepackAccessPolicyDTO loadPolicy() {
        String value = sysParamsService.getValue(PARAM_CODE, true);
        if (StringUtils.isBlank(value)) {
            return defaultPolicy();
        }
        try {
            return normalizePolicy(JsonUtils.parseObject(value, NixiRolepackAccessPolicyDTO.class));
        } catch (Exception ignored) {
            return defaultPolicy();
        }
    }

    private NixiRolepackAccessPolicyDTO normalizePolicy(NixiRolepackAccessPolicyDTO requested) {
        NixiRolepackAccessPolicyDTO normalized = new NixiRolepackAccessPolicyDTO();
        String mode = requested == null ? MODE_OWNER : StringUtils.defaultString(requested.getMode())
                .trim().toLowerCase(Locale.ROOT);
        if (!ALLOWED_MODES.contains(mode)) {
            mode = MODE_OWNER;
        }
        normalized.setMode(mode);

        LinkedHashSet<Long> requestedIds = new LinkedHashSet<>();
        if (requested != null && requested.getWhitelistUserIds() != null) {
            requested.getWhitelistUserIds().stream()
                    .filter(id -> id != null && id > 0)
                    .forEach(requestedIds::add);
        }
        if (!requestedIds.isEmpty()) {
            List<SysUserEntity> users = sysUserDao.selectBatchIds(requestedIds);
            normalized.setWhitelistUserIds(users.stream()
                    .filter(user -> Integer.valueOf(1).equals(user.getStatus()))
                    .filter(user -> !isSuperAdmin(user))
                    .map(SysUserEntity::getId)
                    .collect(Collectors.toList()));
        }
        return normalized;
    }

    private NixiRolepackAccessPolicyDTO defaultPolicy() {
        NixiRolepackAccessPolicyDTO policy = new NixiRolepackAccessPolicyDTO();
        policy.setMode(MODE_OWNER);
        policy.setWhitelistUserIds(new ArrayList<>());
        return policy;
    }

    private boolean isSuperAdmin(SysUserEntity user) {
        return user != null
                && Integer.valueOf(SuperAdminEnum.YES.value()).equals(user.getSuperAdmin());
    }

    private NixiRolepackAccessPolicyVO.UserOption toUserOption(SysUserEntity user) {
        NixiRolepackAccessPolicyVO.UserOption option = new NixiRolepackAccessPolicyVO.UserOption();
        option.setUserId(user.getId());
        option.setUsername(user.getUsername());
        option.setStatus(user.getStatus());
        option.setSuperAdmin(isSuperAdmin(user));
        return option;
    }
}
