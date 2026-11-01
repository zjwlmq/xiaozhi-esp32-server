package xiaozhi.modules.agent.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.exception.ErrorCode;
import xiaozhi.modules.agent.dao.AgentDao;
import xiaozhi.modules.agent.dao.PluginCenterMapper;
import xiaozhi.modules.agent.entity.AgentEntity;
import xiaozhi.modules.device.service.DeviceService;
import java.time.Instant;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class PluginCenterService {
    private final PluginCenterMapper mapper;
    private final AgentDao agentDao;
    private final AgentService agentService;
    private final DeviceService deviceService;
    private final PluginCatalog catalog;
    private final ObjectMapper json;

    private ObjectNode read(String raw) {
        try { return raw == null || raw.isBlank() ? json.createObjectNode() : (ObjectNode) json.readTree(raw); }
        catch (Exception e) { throw new RenException("插件配置读取失败"); }
    }

    private ObjectNode packet(String agentId) {
        ObjectNode packet = read(mapper.loadConfig(agentId));
        if (!packet.has("revision")) packet.put("revision", 0);
        if (!packet.has("plugins")) packet.putObject("plugins");
        ObjectNode states = (ObjectNode) packet.get("plugins");
        for (JsonNode manifest : catalog.catalog().path("plugins")) {
            String id = manifest.path("id").asText();
            if (!states.has(id)) states.set(id, catalog.defaultState(id));
        }
        return packet;
    }

    private void requireAccess(String agentId, Long userId) {
        if (!agentService.checkAgentPermission(agentId, userId)) throw new RenException(ErrorCode.FORBIDDEN);
    }

    public ObjectNode getForUser(String agentId, Long userId) {
        requireAccess(agentId, userId);
        ObjectNode result = packet(agentId);
        ObjectNode states = (ObjectNode) result.get("plugins");
        for (JsonNode manifest : catalog.catalog().path("plugins")) {
            String id = manifest.path("id").asText();
            states.set(id, catalog.redact(id, states.get(id)));
        }
        result.set("catalog", catalog.catalog());
        result.set("runtime", read(mapper.loadStatus(agentId)));
        return result;
    }

    @Transactional(rollbackFor = Exception.class)
    public ObjectNode update(String agentId, String id, JsonNode patch, Long userId) {
        AgentEntity agent = agentDao.selectByIdForUpdate(agentId);
        if (agent == null) throw new RenException(ErrorCode.AGENT_NOT_FOUND);
        requireAccess(agentId, userId);
        JsonNode manifest = catalog.manifest(id);
        ObjectNode packet = packet(agentId);
        ObjectNode states = (ObjectNode) packet.get("plugins");
        ObjectNode next = catalog.merge(id, states.get(id), patch);
        states.set(id, next);
        if (next.path("enabled").asBoolean()) {
            for (JsonNode dependency : manifest.path("dependencies"))
                ((ObjectNode) states.get(dependency.asText())).put("enabled", true);
        } else {
            for (JsonNode candidate : catalog.catalog().path("plugins")) {
                if (!states.path(candidate.path("id").asText()).path("enabled").asBoolean()) continue;
                for (JsonNode dependency : candidate.path("dependencies")) if (dependency.asText().equals(id))
                    throw new RenException("请先关闭依赖它的“" + candidate.path("name").asText() + "”");
            }
        }
        packet.put("revision", packet.path("revision").asLong() + 1);
        mapper.saveConfig(agentId, packet.toString());
        return getForUser(agentId, userId);
    }

    private AgentEntity agentForDevice(String mac) {
        if (mac == null || mac.isBlank() || mac.length() > 100) throw new RenException("设备标识无效");
        var device = deviceService.getDeviceByMacAddress(mac);
        if (device == null) throw new RenException(ErrorCode.OTA_DEVICE_NOT_FOUND);
        AgentEntity agent = agentDao.selectById(device.getAgentId());
        if (agent == null) throw new RenException(ErrorCode.AGENT_NOT_FOUND);
        return agent;
    }

    public ObjectNode getRuntime(String mac) {
        AgentEntity agent = agentForDevice(mac);
        ObjectNode result = packet(agent.getId());
        result.put("scope", "agent:" + agent.getUserId() + ":" + agent.getId() + ":device:" + mac);
        return result;
    }

    public void reportRuntime(String mac, JsonNode report) {
        AgentEntity agent = agentForDevice(mac);
        ObjectNode current = packet(agent.getId());
        if (!report.isObject() || report.path("revision").asLong(-1) != current.path("revision").asLong()) return;
        ObjectNode safe = json.createObjectNode().put("revision", current.path("revision").asLong())
                .put("observed_at", Instant.now().getEpochSecond());
        ObjectNode items = safe.putObject("plugins");
        for (JsonNode manifest : catalog.catalog().path("plugins")) {
            String id = manifest.path("id").asText();
            JsonNode item = report.path("plugins").path(id);
            String state = item.path("state").asText();
            if (!Set.of("ready", "disabled", "needs_config", "waiting", "error").contains(state)) continue;
            String detail = item.path("detail").asText();
            if (detail.length() > 200) detail = detail.substring(0, 200);
            items.putObject(id).put("state", state).put("detail", detail);
        }
        mapper.saveStatus(agent.getId(), safe.toString());
    }
}
