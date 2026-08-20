package xiaozhi.modules.timbre.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "火山引擎上游复刻音色")
public class VolcengineUpstreamVoiceDTO {
    private String speakerId;
    private String name;
    private String state;
    private String cloneVersion;
    private String resourceId;
    private String demoAudio;
    private Long createTime;
    private Long expireTime;
    private boolean imported;
}
