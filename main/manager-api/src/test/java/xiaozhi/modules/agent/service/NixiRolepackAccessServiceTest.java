package xiaozhi.modules.agent.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.List;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import xiaozhi.common.exception.RenException;
import xiaozhi.modules.agent.dto.NixiRolepackAccessPolicyDTO;
import xiaozhi.modules.agent.vo.NixiRolepackAccessPolicyVO;
import xiaozhi.modules.sys.dao.SysUserDao;
import xiaozhi.modules.sys.entity.SysUserEntity;
import xiaozhi.modules.sys.service.SysParamsService;

class NixiRolepackAccessServiceTest {
    private SysParamsService sysParamsService;
    private SysUserDao sysUserDao;
    private NixiRolepackAccessService service;

    @BeforeEach
    void setUp() {
        sysParamsService = mock(SysParamsService.class);
        sysUserDao = mock(SysUserDao.class);
        service = new NixiRolepackAccessService(sysParamsService, sysUserDao);
        when(sysUserDao.selectById(1L)).thenReturn(user(1L, "owner", 1, 1));
        when(sysUserDao.selectById(2L)).thenReturn(user(2L, "allowed", 0, 1));
        when(sysUserDao.selectById(3L)).thenReturn(user(3L, "denied", 0, 1));
    }

    @Test
    void missingOrInvalidPolicyFailsClosedToSuperAdminOnly() {
        when(sysParamsService.getValue(NixiRolepackAccessService.PARAM_CODE, true)).thenReturn(null);
        assertTrue(service.isAllowed(1L));
        assertFalse(service.isAllowed(2L));

        when(sysParamsService.getValue(NixiRolepackAccessService.PARAM_CODE, true))
                .thenReturn("{\"mode\":\"invalid\",\"whitelistUserIds\":[2]}");
        when(sysUserDao.selectBatchIds(anyCollection())).thenReturn(List.of(user(2L, "allowed", 0, 1)));
        assertFalse(service.isAllowed(2L));
    }

    @Test
    void whitelistAllowsSelectedActiveUsersAndAlwaysAllowsSuperAdmin() {
        when(sysParamsService.getValue(NixiRolepackAccessService.PARAM_CODE, true))
                .thenReturn("{\"mode\":\"whitelist\",\"whitelistUserIds\":[2]}");
        when(sysUserDao.selectBatchIds(anyCollection())).thenReturn(List.of(user(2L, "allowed", 0, 1)));

        assertTrue(service.isAllowed(1L));
        assertTrue(service.isAllowed(2L));
        assertFalse(service.isAllowed(3L));
    }

    @Test
    void publicAllowsEveryActiveUserButNotDisabledAccounts() {
        when(sysParamsService.getValue(NixiRolepackAccessService.PARAM_CODE, true))
                .thenReturn("{\"mode\":\"public\",\"whitelistUserIds\":[]}");
        when(sysUserDao.selectById(4L)).thenReturn(user(4L, "disabled", 0, 0));

        assertTrue(service.isAllowed(2L));
        assertFalse(service.isAllowed(4L));
    }

    @Test
    void saveAndRuntimeChecksCannotBeBypassedByTypingDirective() {
        when(sysParamsService.getValue(NixiRolepackAccessService.PARAM_CODE, true)).thenReturn(null);
        String directive = "@rolepack nixi/duo\ncanon=novel";

        assertTrue(service.isNixiPrompt(directive));
        assertThrows(RenException.class, () -> service.assertPromptAllowed(2L, directive));
        assertEquals(NixiRolepackAccessService.DENIED_PROMPT,
                service.enforceRuntimePrompt(2L, directive));
        assertEquals("ordinary prompt", service.enforceRuntimePrompt(2L, "ordinary prompt"));
    }

    @Test
    void normalUsersSeeTheirStatusButNotTheWhitelistOrAccountDirectory() {
        when(sysParamsService.getValue(NixiRolepackAccessService.PARAM_CODE, true))
                .thenReturn("{\"mode\":\"whitelist\",\"whitelistUserIds\":[2,3]}");
        when(sysUserDao.selectBatchIds(anyCollection()))
                .thenReturn(List.of(user(2L, "allowed", 0, 1), user(3L, "denied", 0, 1)));

        NixiRolepackAccessPolicyVO view = service.getPolicyView(2L);

        assertTrue(view.isCurrentUserAllowed());
        assertFalse(view.isEditable());
        assertTrue(view.getWhitelistUserIds().isEmpty());
        assertTrue(view.getUsers().isEmpty());
    }

    @Test
    void savingAnUnchangedPolicyStillSucceedsWhenTheDatabaseValueMatches() {
        String json = "{\"mode\":\"public\",\"whitelistUserIds\":[]}";
        when(sysParamsService.getValue(NixiRolepackAccessService.PARAM_CODE, false)).thenReturn(json);
        when(sysParamsService.getValue(NixiRolepackAccessService.PARAM_CODE, true)).thenReturn(json);
        when(sysParamsService.updateValueByCode(NixiRolepackAccessService.PARAM_CODE, json)).thenReturn(0);
        when(sysUserDao.selectList(any())).thenReturn(List.of(user(1L, "owner", 1, 1)));
        NixiRolepackAccessPolicyDTO requested = new NixiRolepackAccessPolicyDTO();
        requested.setMode(NixiRolepackAccessService.MODE_PUBLIC);

        NixiRolepackAccessPolicyVO view = service.savePolicy(1L, requested);

        assertEquals(NixiRolepackAccessService.MODE_PUBLIC, view.getMode());
        assertTrue(view.isEditable());
        assertTrue(view.isCurrentUserAllowed());
    }

    private static SysUserEntity user(Long id, String username, int superAdmin, int status) {
        SysUserEntity user = new SysUserEntity();
        user.setId(id);
        user.setUsername(username);
        user.setSuperAdmin(superAdmin);
        user.setStatus(status);
        return user;
    }
}
