package xiaozhi.modules.agent.vo;

import java.util.ArrayList;
import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "《逆袭》角色包访问策略视图")
public class NixiRolepackAccessPolicyVO {
    private String mode;
    private List<Long> whitelistUserIds = new ArrayList<>();
    private boolean currentUserAllowed;
    private boolean editable;
    private List<UserOption> users = new ArrayList<>();

    @Data
    public static class UserOption {
        private Long userId;
        private String username;
        private Integer status;
        private boolean superAdmin;
    }
}
