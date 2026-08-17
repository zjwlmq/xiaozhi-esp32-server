package xiaozhi.modules.model.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Schema(description = "上游模型信息")
public class UpstreamModelInfoDTO {
    private String id;
    private String name;
}
