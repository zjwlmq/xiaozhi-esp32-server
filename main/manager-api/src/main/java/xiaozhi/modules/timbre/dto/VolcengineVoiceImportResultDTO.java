package xiaozhi.modules.timbre.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "火山引擎复刻音色导入结果")
public class VolcengineVoiceImportResultDTO {
    private int importedCount;
    private int skippedCount;
}
