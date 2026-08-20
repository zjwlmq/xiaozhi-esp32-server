package xiaozhi.modules.timbre.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "火山引擎复刻音色同步请求")
public class VolcengineVoiceSyncRequestDTO {
    @Schema(description = "导入目标 TTS 模型ID")
    private String ttsModelId;

    @Schema(description = "声音复刻版本：1.0 或 2.0")
    private String cloneVersion;
}
