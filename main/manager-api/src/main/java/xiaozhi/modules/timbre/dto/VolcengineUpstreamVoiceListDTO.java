package xiaozhi.modules.timbre.dto;

import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "火山引擎上游复刻音色列表")
public class VolcengineUpstreamVoiceListDTO {
    private String cloneVersion;
    private String resourceId;
    private List<VolcengineUpstreamVoiceDTO> voices;
    private int total;
}
