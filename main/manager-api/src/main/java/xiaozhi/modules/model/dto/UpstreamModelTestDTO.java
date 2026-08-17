package xiaozhi.modules.model.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "上游模型连接测试结果")
public class UpstreamModelTestDTO {
    private boolean success;
    private String model;
    private String response;
    private String requestId;
    private long latencyMs;
    private int upstreamStatus;
    private String endpoint;
}
