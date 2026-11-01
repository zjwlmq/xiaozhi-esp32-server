package xiaozhi.modules.agent.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.RequiredArgsConstructor;
import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.springframework.web.bind.annotation.*;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.security.user.SecurityUser;
import xiaozhi.modules.agent.service.PluginCenterService;

@RestController
@RequestMapping("/agent/{agentId}/plugin-center")
@RequiredArgsConstructor
public class PluginCenterController {
    private final PluginCenterService service;

    @GetMapping
    @RequiresPermissions("sys:role:normal")
    public Result<ObjectNode> get(@PathVariable String agentId) {
        return new Result<ObjectNode>().ok(service.getForUser(agentId, SecurityUser.getUserId()));
    }

    @PutMapping("/{pluginId}")
    @RequiresPermissions("sys:role:normal")
    public Result<ObjectNode> update(@PathVariable String agentId, @PathVariable String pluginId, @RequestBody JsonNode patch) {
        return new Result<ObjectNode>().ok(service.update(agentId, pluginId, patch, SecurityUser.getUserId()));
    }
}
