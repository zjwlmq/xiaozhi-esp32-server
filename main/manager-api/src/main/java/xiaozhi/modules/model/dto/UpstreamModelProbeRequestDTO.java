package xiaozhi.modules.model.dto;

import cn.hutool.json.JSONObject;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "上游模型获取/连接测试请求")
public class UpstreamModelProbeRequestDTO {

    @Schema(description = "已保存的模型配置ID，用于在后端恢复被掩码的密钥")
    private String modelId;

    @Schema(description = "当前表单中的调用配置")
    private JSONObject configJson;

    @Schema(description = "待测试的上游模型名称")
    private String modelName;

    @Schema(description = "测试消息，默认 hi")
    private String prompt;
}
