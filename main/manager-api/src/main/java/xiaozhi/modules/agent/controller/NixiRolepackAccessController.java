package xiaozhi.modules.agent.controller;

import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.AllArgsConstructor;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.agent.dto.NixiRolepackAccessPolicyDTO;
import xiaozhi.modules.agent.service.NixiRolepackAccessService;
import xiaozhi.modules.agent.vo.NixiRolepackAccessPolicyVO;
import xiaozhi.modules.security.user.SecurityUser;

@RestController
@RequestMapping("/nixi-rolepack/access-policy")
@Tag(name = "《逆袭》角色包访问策略")
@AllArgsConstructor
public class NixiRolepackAccessController {
    private final NixiRolepackAccessService accessService;

    @GetMapping
    @Operation(summary = "获取当前账号的角色包访问状态")
    @RequiresPermissions("sys:role:normal")
    public Result<NixiRolepackAccessPolicyVO> get() {
        return new Result<NixiRolepackAccessPolicyVO>().ok(
                accessService.getPolicyView(SecurityUser.getUserId()));
    }

    @PutMapping
    @Operation(summary = "修改角色包访问策略")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<NixiRolepackAccessPolicyVO> update(
            @RequestBody NixiRolepackAccessPolicyDTO policy) {
        return new Result<NixiRolepackAccessPolicyVO>().ok(
                accessService.savePolicy(SecurityUser.getUserId(), policy));
    }
}
