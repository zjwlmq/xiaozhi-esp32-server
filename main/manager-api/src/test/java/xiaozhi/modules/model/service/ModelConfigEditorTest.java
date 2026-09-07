package xiaozhi.modules.model.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.util.List;

import cn.hutool.json.JSONObject;
import org.apache.shiro.authz.UnauthorizedException;
import org.apache.shiro.spring.security.interceptor.AuthorizationAttributeSourceAdvisor;
import org.apache.shiro.subject.Subject;
import org.apache.shiro.util.ThreadContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.util.ReflectionTestUtils;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.redis.RedisUtils;
import xiaozhi.common.utils.SensitiveDataUtils;
import xiaozhi.modules.agent.dao.AgentDao;
import xiaozhi.modules.model.controller.ModelController;
import xiaozhi.modules.model.dao.ModelConfigDao;
import xiaozhi.modules.model.dto.ModelConfigBodyDTO;
import xiaozhi.modules.model.dto.ModelConfigDTO;
import xiaozhi.modules.model.dto.ModelProviderDTO;
import xiaozhi.modules.model.entity.ModelConfigEntity;
import xiaozhi.modules.model.service.impl.ModelConfigServiceImpl;

class ModelConfigEditorTest {
    private ModelConfigDao dao;
    private ModelConfigServiceImpl service;
    private ModelConfigEntity saved;

    @BeforeEach
    void setUp() {
        dao = mock(ModelConfigDao.class);
        ModelProviderService providers = mock(ModelProviderService.class);
        when(providers.getList(anyString(), anyString())).thenReturn(List.of(new ModelProviderDTO()));
        service = new ModelConfigServiceImpl(dao, providers, mock(RedisUtils.class), mock(AgentDao.class));
        ReflectionTestUtils.setField(service, "baseDao", dao);
        saved = new ModelConfigEntity();
        saved.setId("unchanged-internal-id");
        saved.setModelName("claude_副本");
        saved.setModelCode("ClaudeCopy");
        saved.setModelType("llm");
        saved.setIsEnabled(1);
        saved.setConfigJson(new JSONObject().set("type", "anthropic_messages")
                .set("api_key", "sk-offline-test-secret").set("access_key_secret", "ak-offline-test-secret"));
        when(dao.selectById(saved.getId())).thenReturn(saved);
    }

    @AfterEach
    void clearSubject() {
        ThreadContext.unbindSubject();
    }

    @Test
    void editorRevealsOnlyApiKeyWithoutChangingStoredObjectOrBinding() {
        ModelConfigDTO result = service.getModelForEditor(saved.getId());
        assertEquals(saved.getId(), result.getId());
        assertEquals("claude_副本", result.getModelName());
        assertEquals("sk-offline-test-secret", result.getConfigJson().getStr("api_key"));
        assertTrue(SensitiveDataUtils.isMaskedValue(result.getConfigJson().getStr("access_key_secret")));
        assertEquals("ak-offline-test-secret", saved.getConfigJson().getStr("access_key_secret"));
        result.getConfigJson().set("api_key", "edited-only-in-form");
        assertEquals("sk-offline-test-secret", saved.getConfigJson().getStr("api_key"));
    }

    @Test
    void oldDetailEndpointStillReceivesMaskedKeys() {
        assertTrue(SensitiveDataUtils.isMaskedValue(service.selectById(saved.getId()).getConfigJson().getStr("api_key")));
    }

    @Test
    void editorCanShowAnEmptyKeyOrOldPlaceholderTruthfully() {
        for (String key : List.of("", "你的API密钥")) {
            saved.getConfigJson().set("api_key", key);
            assertEquals(key, service.getModelForEditor(saved.getId()).getConfigJson().getStr("api_key"));
        }
    }

    @Test
    void enabledAnthropicCannotSaveAnEmptyOrPlaceholderKeyAndErrorsNameTheModel() {
        for (String key : List.of("", "你的API密钥", "your_api_key", "sk-private\ninvalid")) {
            RenException error = assertThrows(RenException.class,
                    () -> service.edit("llm", "anthropic_messages", saved.getId(), body(key, 1)));
            assertTrue(error.getMessage().contains("claude_副本"));
            if (!key.isEmpty()) assertFalse(error.getMessage().contains(key));
        }
        verify(dao, never()).updateById(any(ModelConfigEntity.class));
    }

    @Test
    void aDisabledDraftMaySaveAnExplicitlyClearedKey() {
        ModelConfigDTO result = service.edit("llm", "anthropic_messages", saved.getId(), body("", 0));
        assertEquals(saved.getId(), result.getId());
        assertEquals("", result.getConfigJson().getStr("api_key"));
    }

    @Test
    void savingRealOrMaskedKeyRetainsBindingsAndMasksTheSaveResponse() {
        ModelConfigDTO result = service.edit("llm", "anthropic_messages", saved.getId(), body("sk-updated-test-secret", 1));
        assertEquals(saved.getId(), result.getId());
        assertTrue(SensitiveDataUtils.isMaskedValue(result.getConfigJson().getStr("api_key")));
        ModelConfigDTO unchanged = service.edit("llm", "anthropic_messages", saved.getId(), body("sk-o********cret", 1));
        assertEquals(SensitiveDataUtils.maskMiddle("sk-offline-test-secret"), unchanged.getConfigJson().getStr("api_key"));
    }

    @Test
    void addingEnabledCopyWithPlaceholderIsRejectedBeforeInsert() {
        for (String key : List.of("你的API密钥", "sk-****masked")) {
            assertThrows(RenException.class, () -> service.add("llm", "anthropic_messages", body(key, 1)));
        }
        verify(dao, never()).insert(any(ModelConfigEntity.class));
    }

    @Test
    void nonAdminCannotInvokeEditorEndpointThroughShiroAdvisor() {
        Subject subject = mock(Subject.class);
        doThrow(new UnauthorizedException()).when(subject).checkPermission("sys:role:superAdmin");
        ThreadContext.bind(subject);
        ModelConfigService mockService = mock(ModelConfigService.class);
        ModelController controller = securedController(mockService);
        assertThrows(UnauthorizedException.class,
                () -> controller.getModelForEditor(saved.getId(), new MockHttpServletResponse()));
        verifyNoInteractions(mockService);
    }

    @Test
    void authorizedEditorResponseIsNotCacheable() {
        ThreadContext.bind(mock(Subject.class));
        ModelConfigService mockService = mock(ModelConfigService.class);
        when(mockService.getModelForEditor(saved.getId())).thenReturn(service.getModelForEditor(saved.getId()));
        MockHttpServletResponse response = new MockHttpServletResponse();
        ModelConfigDTO result = securedController(mockService).getModelForEditor(saved.getId(), response).getData();
        assertEquals("sk-offline-test-secret", result.getConfigJson().getStr("api_key"));
        assertEquals("no-store, private", response.getHeader("Cache-Control"));
        assertEquals("no-cache", response.getHeader("Pragma"));
    }

    private ModelController securedController(ModelConfigService configService) {
        ModelController controller = new ModelController(null, null, configService, null, null, null);
        ProxyFactory factory = new ProxyFactory(controller);
        factory.addAdvisor(new AuthorizationAttributeSourceAdvisor());
        return (ModelController) factory.getProxy();
    }

    private ModelConfigBodyDTO body(String key, int enabled) {
        ModelConfigBodyDTO body = new ModelConfigBodyDTO();
        body.setId(saved.getId());
        body.setModelName("claude_副本");
        body.setModelCode("ClaudeCopy");
        body.setIsEnabled(enabled);
        body.setConfigJson(new JSONObject().set("type", "anthropic_messages").set("api_key", key));
        return body;
    }
}
