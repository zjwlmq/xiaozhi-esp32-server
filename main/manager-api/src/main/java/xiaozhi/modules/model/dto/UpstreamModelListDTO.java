package xiaozhi.modules.model.dto;

import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "上游模型列表结果")
public class UpstreamModelListDTO {
    private List<UpstreamModelInfoDTO> models;
    private long latencyMs;
    private int upstreamStatus;
    private String endpoint;
}
