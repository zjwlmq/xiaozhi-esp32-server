package xiaozhi.modules.agent.dto;

import java.util.ArrayList;
import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "《逆袭》角色包访问策略")
public class NixiRolepackAccessPolicyDTO {
    @Schema(description = "访问模式：owner、whitelist、public")
    private String mode = "owner";

    @Schema(description = "白名单普通用户 ID；超级管理员始终允许")
    private List<Long> whitelistUserIds = new ArrayList<>();
}
