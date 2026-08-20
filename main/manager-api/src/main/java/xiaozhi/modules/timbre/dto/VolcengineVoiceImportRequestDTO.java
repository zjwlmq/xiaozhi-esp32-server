package xiaozhi.modules.timbre.dto;

import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = true)
@Schema(description = "火山引擎复刻音色导入请求")
public class VolcengineVoiceImportRequestDTO extends VolcengineVoiceSyncRequestDTO {
    @Schema(description = "要导入的 SpeakerID 列表")
    private List<String> speakerIds;
}
