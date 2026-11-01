package xiaozhi.modules.agent.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.utils.MessageUtils;
import xiaozhi.modules.agent.dao.AgentDao;
import xiaozhi.modules.agent.dao.PluginCenterMapper;
import xiaozhi.modules.agent.entity.AgentEntity;
import xiaozhi.modules.device.entity.DeviceEntity;
import xiaozhi.modules.device.service.DeviceService;
import java.util.concurrent.atomic.AtomicReference;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class PluginCenterServiceTest {
    private final ObjectMapper json=new ObjectMapper();
    private PluginCenterMapper mapper;
    private AgentDao agents;
    private AgentService access;
    private DeviceService devices;
    private PluginCenterService service;
    private MockedStatic<MessageUtils> messages;
    private final AtomicReference<String> saved=new AtomicReference<>();
    private final AtomicReference<String> status=new AtomicReference<>();

    @BeforeEach void setup() {
        messages=mockStatic(MessageUtils.class);
        messages.when(()->MessageUtils.getMessage(anyInt())).thenReturn("test error");
        mapper=mock(PluginCenterMapper.class); agents=mock(AgentDao.class);
        access=mock(AgentService.class); devices=mock(DeviceService.class);
        AgentEntity agent=new AgentEntity(); agent.setId("agent-a"); agent.setUserId(7L);
        when(agents.selectByIdForUpdate("agent-a")).thenReturn(agent);
        when(agents.selectById("agent-a")).thenReturn(agent);
        when(access.checkAgentPermission("agent-a",7L)).thenReturn(true);
        when(mapper.loadConfig("agent-a")).thenAnswer(invocation -> saved.get());
        when(mapper.loadStatus("agent-a")).thenAnswer(invocation -> status.get());
        doAnswer(invocation -> {saved.set(invocation.getArgument(1));return null;}).when(mapper).saveConfig(eq("agent-a"),anyString());
        doAnswer(invocation -> {status.set(invocation.getArgument(1));return null;}).when(mapper).saveStatus(eq("agent-a"),anyString());
        DeviceEntity device=new DeviceEntity();device.setAgentId("agent-a");
        when(devices.getDeviceByMacAddress("device-a")).thenReturn(device);
        service=new PluginCenterService(mapper,agents,access,devices,new PluginCatalog(),json);
    }

    @AfterEach void cleanup() { messages.close(); }

    @Test void switchingOnePluginPersistsAndPreservesOtherSettings() throws Exception {
        ObjectNode first=service.update("agent-a","holiday-awareness",json.readTree("{\"enabled\":true}"),7L);
        assertTrue(first.path("plugins").path("time-awareness").path("enabled").asBoolean());
        assertEquals(1,first.path("revision").asInt());
        service.update("agent-a","memory-optimizer",json.readTree("{\"enabled\":true,\"settings\":{\"max_characters\":1500}}"),7L);
        var read=service.getForUser("agent-a",7L);
        assertTrue(read.path("plugins").path("holiday-awareness").path("enabled").asBoolean());
        assertEquals(1500,read.path("plugins").path("memory-optimizer").path("settings").path("max_characters").asInt());
        assertEquals(2,read.path("revision").asInt());
    }

    @Test void dependencyCannotBeRemovedWhileDependentIsEnabled() throws Exception {
        service.update("agent-a","proactive-messaging",json.readTree("{\"enabled\":true}"),7L);
        String before=saved.get();
        assertThrows(RenException.class,()->service.update("agent-a","time-awareness",json.readTree("{\"enabled\":false}"),7L));
        assertEquals(before,saved.get());
        service.update("agent-a","proactive-messaging",json.readTree("{\"enabled\":false}"),7L);
        assertFalse(service.update("agent-a","time-awareness",json.readTree("{\"enabled\":false}"),7L).path("plugins").path("time-awareness").path("enabled").asBoolean());
    }

    @Test void unauthorizedUserCannotReadOrWriteAnyConfig() {
        assertThrows(RenException.class,()->service.getForUser("agent-a",8L));
        assertThrows(RenException.class,()->service.update("agent-a","time-awareness",json.createObjectNode().put("enabled",true),8L));
        verifyNoInteractions(mapper);
    }

    @Test void browserReadIsRedactedButBoundDeviceReceivesItsOwnCredentials() throws Exception {
        var ui=service.update("agent-a","image-generation",json.readTree("{\"settings\":{\"api_key\":\"private-test-key\"}}"),7L);
        assertFalse(ui.toString().contains("private-test-key"));
        assertEquals("private-test-key",service.getRuntime("device-a").path("plugins").path("image-generation").path("settings").path("api_key").asText());
        assertTrue(service.getRuntime("device-a").path("scope").asText().contains("agent:7:agent-a:device:device-a"));
        assertThrows(RenException.class,()->service.getRuntime("unbound"));
    }

    @Test void staleRuntimeCannotClaimLatestSettingsAreRunning() throws Exception {
        service.update("agent-a","time-awareness",json.readTree("{\"enabled\":true}"),7L);
        service.reportRuntime("device-a",json.readTree("{\"revision\":0,\"plugins\":{\"time-awareness\":{\"state\":\"ready\",\"detail\":\"old\"}}}"));
        assertNull(status.get());
        service.reportRuntime("device-a",json.readTree("{\"revision\":1,\"plugins\":{\"time-awareness\":{\"state\":\"ready\",\"detail\":\"已加载\",\"api_key\":\"do-not-copy\"}}}"));
        assertNotNull(status.get());
        assertFalse(status.get().contains("do-not-copy"));
        assertTrue(service.getForUser("agent-a",7L).path("runtime").path("observed_at").asLong()>0);
    }
}
