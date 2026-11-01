package xiaozhi.modules.config.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.agent.service.PluginCenterService;

/** /config/** is protected by ServerSecretFilter; secrets never use the user-facing API. */
@RestController
@RequestMapping("/config/agent-plugins")
@RequiredArgsConstructor
public class PluginRuntimeController {
    private final PluginCenterService service;

    @PostMapping
    public Result<ObjectNode> get(@RequestBody JsonNode request) {
        return new Result<ObjectNode>().ok(service.getRuntime(request.path("macAddress").asText()));
    }

    @PostMapping("/status")
    public Result<Void> report(@RequestBody JsonNode request) {
        service.reportRuntime(request.path("macAddress").asText(), request.path("status"));
        return new Result<Void>().ok(null);
    }
}
