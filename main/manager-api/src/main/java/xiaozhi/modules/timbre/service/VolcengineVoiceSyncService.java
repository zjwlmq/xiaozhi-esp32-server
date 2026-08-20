package xiaozhi.modules.timbre.service;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import cn.hutool.json.JSONObject;
import xiaozhi.common.constant.Constant;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.model.dao.ModelConfigDao;
import xiaozhi.modules.model.entity.ModelConfigEntity;
import xiaozhi.modules.model.dto.VoiceDTO;
import xiaozhi.modules.timbre.dto.TimbreDataDTO;
import xiaozhi.modules.timbre.dto.VolcengineUpstreamVoiceDTO;
import xiaozhi.modules.timbre.dto.VolcengineUpstreamVoiceListDTO;
import xiaozhi.modules.timbre.dto.VolcengineVoiceImportRequestDTO;
import xiaozhi.modules.timbre.dto.VolcengineVoiceImportResultDTO;
import xiaozhi.modules.timbre.dto.VolcengineVoiceSyncRequestDTO;

/**
 * 从火山引擎 OpenAPI 手动同步声音复刻音色。AK/SK 仅由后端读取并签名，
 * 不返回浏览器；导入时重新查询上游，避免信任前端提交的名称和试听地址。
 */
@Service
public class VolcengineVoiceSyncService {

    private static final String SERVICE = "speech_saas_prod";
    private static final String REGION = "cn-north-1";
    private static final String ACTION = "BatchListMegaTTSTrainStatus";
    private static final String API_VERSION = "2023-11-07";
    private static final String SIGN_ALGORITHM = "HMAC-SHA256";
    private static final String CONTENT_TYPE = "application/json; charset=utf-8";
    private static final int PAGE_SIZE = 100;
    private static final int MAX_PAGES = 20;
    private static final int MAX_RESPONSE_CHARS = 1_000_000;
    private static final Duration CONNECT_TIMEOUT = Duration.ofSeconds(10);
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(30);
    private static final DateTimeFormatter X_DATE = DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss'Z'")
            .withZone(ZoneOffset.UTC);
    private static final DateTimeFormatter SHORT_DATE = DateTimeFormatter.ofPattern("yyyyMMdd")
            .withZone(ZoneOffset.UTC);

    private final ModelConfigDao modelConfigDao;
    private final TimbreService timbreService;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;
    private final URI endpoint;
    private final Clock clock;

    @Autowired
    public VolcengineVoiceSyncService(ModelConfigDao modelConfigDao, TimbreService timbreService,
            ObjectMapper objectMapper) {
        this(modelConfigDao, timbreService, objectMapper,
                HttpClient.newBuilder().connectTimeout(CONNECT_TIMEOUT)
                        .followRedirects(HttpClient.Redirect.NEVER).build(),
                URI.create("https://open.volcengineapi.com/"), Clock.systemUTC());
    }

    VolcengineVoiceSyncService(ModelConfigDao modelConfigDao, TimbreService timbreService,
            ObjectMapper objectMapper, HttpClient httpClient, URI endpoint, Clock clock) {
        this.modelConfigDao = modelConfigDao;
        this.timbreService = timbreService;
        this.objectMapper = objectMapper;
        this.httpClient = httpClient;
        this.endpoint = endpoint;
        this.clock = clock;
    }

    public VolcengineUpstreamVoiceListDTO fetchVoices(VolcengineVoiceSyncRequestDTO request) {
        ResolvedConfig resolved = resolve(request);
        List<VolcengineUpstreamVoiceDTO> voices = fetchAll(resolved);
        for (VolcengineUpstreamVoiceDTO voice : voices) {
            VoiceDTO existing = timbreService.getByVoiceCode(resolved.modelId(), voice.getSpeakerId());
            voice.setImported(existing != null);
        }
        voices.sort(Comparator.comparing(VolcengineUpstreamVoiceDTO::getCreateTime,
                Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(VolcengineUpstreamVoiceDTO::getSpeakerId));

        VolcengineUpstreamVoiceListDTO result = new VolcengineUpstreamVoiceListDTO();
        result.setCloneVersion(resolved.cloneVersion());
        result.setResourceId(resolved.resourceId());
        result.setVoices(voices);
        result.setTotal(voices.size());
        return result;
    }

    @Transactional(rollbackFor = Exception.class)
    public VolcengineVoiceImportResultDTO importVoices(VolcengineVoiceImportRequestDTO request) {
        if (request == null || request.getSpeakerIds() == null || request.getSpeakerIds().isEmpty()) {
            throw new RenException("请至少选择一个要导入的音色");
        }
        Set<String> requestedIds = new HashSet<>();
        for (String speakerId : request.getSpeakerIds()) {
            String normalized = StringUtils.trim(speakerId);
            if (StringUtils.isBlank(normalized) || !normalized.startsWith("S_")) {
                throw new RenException("SpeakerID 格式无效，只允许导入 S_ 开头的复刻音色");
            }
            requestedIds.add(normalized);
        }
        if (requestedIds.size() > PAGE_SIZE) {
            throw new RenException("单次最多导入100个音色");
        }

        ResolvedConfig resolved = resolve(request);
        Map<String, VolcengineUpstreamVoiceDTO> upstream = new HashMap<>();
        for (VolcengineUpstreamVoiceDTO voice : fetchAll(resolved)) {
            upstream.put(voice.getSpeakerId(), voice);
        }

        int imported = 0;
        int skipped = 0;
        for (String speakerId : requestedIds) {
            VolcengineUpstreamVoiceDTO voice = upstream.get(speakerId);
            if (voice == null) {
                throw new RenException("上游未返回与所选复刻版本匹配的音色：" + speakerId);
            }
            if (!isReady(voice.getState())) {
                throw new RenException("音色尚未训练完成或已不可用：" + speakerId + "（" + voice.getState() + "）");
            }
            if (timbreService.getByVoiceCode(resolved.modelId(), speakerId) != null) {
                skipped++;
                continue;
            }

            TimbreDataDTO dto = new TimbreDataDTO();
            dto.setTtsModelId(resolved.modelId());
            dto.setTtsVoice(speakerId);
            dto.setName(StringUtils.defaultIfBlank(voice.getName(), speakerId));
            dto.setLanguages("中文");
            dto.setVoiceDemo(StringUtils.defaultString(voice.getDemoAudio()));
            dto.setRemark("火山上游同步 · 声音复刻 " + resolved.cloneVersion());
            dto.setUpstreamResourceId(resolved.resourceId());
            dto.setSort(0L);
            timbreService.save(dto);
            imported++;
        }

        VolcengineVoiceImportResultDTO result = new VolcengineVoiceImportResultDTO();
        result.setImportedCount(imported);
        result.setSkippedCount(skipped);
        return result;
    }

    private ResolvedConfig resolve(VolcengineVoiceSyncRequestDTO request) {
        if (request == null || StringUtils.isBlank(request.getTtsModelId())) {
            throw new RenException("目标 TTS 模型不能为空");
        }
        String cloneVersion = normalizeCloneVersion(request.getCloneVersion());
        ModelConfigEntity model = modelConfigDao.selectById(request.getTtsModelId());
        if (model == null || model.getConfigJson() == null) {
            throw new RenException("TTS 模型配置不存在");
        }
        JSONObject config = model.getConfigJson();
        if (!Constant.VOICE_CLONE_HUOSHAN_DOUBLE_STREAM.equals(config.getStr("type"))) {
            throw new RenException("当前 TTS 模型不是火山引擎流式语音合成");
        }
        String appId = StringUtils.trim(config.getStr("appid"));
        String accessKeyId = StringUtils.trim(config.getStr("access_key_id"));
        String accessKeySecret = StringUtils.trim(config.getStr("access_key_secret"));
        if (StringUtils.isBlank(appId)) {
            throw new RenException("请先在模型配置中填写应用ID");
        }
        if (StringUtils.isAnyBlank(accessKeyId, accessKeySecret)) {
            throw new RenException("请先在模型配置中填写 OpenAPI Access Key ID 和 Secret");
        }
        return new ResolvedConfig(model.getId(), cloneVersion, resourceId(cloneVersion),
                appId, accessKeyId, accessKeySecret);
    }

    private List<VolcengineUpstreamVoiceDTO> fetchAll(ResolvedConfig config) {
        Map<String, VolcengineUpstreamVoiceDTO> unique = new LinkedHashMap<>();
        String nextToken = null;
        for (int page = 1; page <= MAX_PAGES; page++) {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("AppID", config.appId());
            if (StringUtils.isNotBlank(nextToken)) {
                payload.put("NextToken", nextToken);
                payload.put("MaxResults", PAGE_SIZE);
            } else {
                payload.put("PageNumber", page);
                payload.put("PageSize", PAGE_SIZE);
            }
            JsonNode result = requestPage(config, payload);
            JsonNode statuses = result.path("Statuses");
            if (!statuses.isArray()) {
                statuses = result.path("SpeakerStatuses");
            }
            if (statuses.isArray()) {
                for (JsonNode status : statuses) {
                    VolcengineUpstreamVoiceDTO voice = parseVoice(status, config);
                    if (voice != null) {
                        unique.putIfAbsent(voice.getSpeakerId(), voice);
                    }
                }
            }
            nextToken = text(result, "NextToken");
            if (StringUtils.isBlank(nextToken) && (!statuses.isArray() || statuses.size() < PAGE_SIZE)) {
                break;
            }
            if (page == MAX_PAGES) {
                throw new RenException("上游音色超过2000条，请缩小账号范围后再同步");
            }
        }
        return new ArrayList<>(unique.values());
    }

    private JsonNode requestPage(ResolvedConfig config, Map<String, Object> payload) {
        try {
            String body = objectMapper.writeValueAsString(payload);
            Instant now = clock.instant();
            String xDate = X_DATE.format(now);
            String shortDate = SHORT_DATE.format(now);
            String bodyHash = sha256Hex(body.getBytes(StandardCharsets.UTF_8));
            String query = "Action=" + ACTION + "&Version=" + API_VERSION;
            String host = endpoint.getAuthority();
            String canonicalHeaders = "content-type:" + CONTENT_TYPE + "\n"
                    + "host:" + host + "\n"
                    + "x-content-sha256:" + bodyHash + "\n"
                    + "x-date:" + xDate + "\n";
            String signedHeaders = "content-type;host;x-content-sha256;x-date";
            String canonicalRequest = "POST\n/\n" + query + "\n" + canonicalHeaders + "\n"
                    + signedHeaders + "\n" + bodyHash;
            String credentialScope = shortDate + "/" + REGION + "/" + SERVICE + "/request";
            String stringToSign = SIGN_ALGORITHM + "\n" + xDate + "\n" + credentialScope + "\n"
                    + sha256Hex(canonicalRequest.getBytes(StandardCharsets.UTF_8));
            byte[] signingKey = signingKey(config.accessKeySecret(), shortDate);
            String signature = hex(hmac(signingKey, stringToSign));
            String authorization = SIGN_ALGORITHM + " Credential=" + config.accessKeyId() + "/"
                    + credentialScope + ", SignedHeaders=" + signedHeaders + ", Signature=" + signature;

            URI uri = URI.create(endpoint.toString() + (endpoint.toString().contains("?") ? "&" : "?") + query);
            HttpRequest request = HttpRequest.newBuilder(uri)
                    .timeout(REQUEST_TIMEOUT)
                    .header("Content-Type", CONTENT_TYPE)
                    .header("X-Date", xDate)
                    .header("X-Content-Sha256", bodyHash)
                    .header("Authorization", authorization)
                    .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = httpClient.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.body() != null && response.body().length() > MAX_RESPONSE_CHARS) {
                throw new RenException("火山上游响应过大，已停止处理");
            }
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                throw new RenException("获取火山上游音色失败：HTTP " + response.statusCode() + " - "
                        + excerpt(response.body()));
            }
            JsonNode root = objectMapper.readTree(response.body());
            JsonNode error = root.path("ResponseMetadata").path("Error");
            if (!error.isMissingNode() && !error.isNull()) {
                throw new RenException("获取火山上游音色失败：" + text(error, "Code") + " - "
                        + text(error, "Message"));
            }
            JsonNode result = root.path("Result");
            if (!result.isObject()) {
                throw new RenException("火山上游响应缺少 Result");
            }
            return result;
        } catch (HttpTimeoutException e) {
            throw new RenException("获取火山上游音色超时");
        } catch (IOException e) {
            throw new RenException("无法连接火山上游：" + safeMessage(e));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new RenException("获取火山上游音色被中断");
        } catch (RenException e) {
            throw e;
        } catch (Exception e) {
            throw new RenException("生成火山 OpenAPI 请求失败：" + safeMessage(e));
        }
    }

    private VolcengineUpstreamVoiceDTO parseVoice(JsonNode status, ResolvedConfig config) {
        String speakerId = text(status, "SpeakerID", "speaker_id");
        if (StringUtils.isBlank(speakerId) || !speakerId.startsWith("S_")) {
            return null;
        }
        JsonNode detail = matchingModelDetail(status.path("ModelTypeDetails"), config.resourceId());
        if (detail == null) {
            String directResourceId = text(status, "ResourceID", "ResourceId", "resource_id");
            if (!config.resourceId().equals(directResourceId)) {
                return null;
            }
        }
        VolcengineUpstreamVoiceDTO voice = new VolcengineUpstreamVoiceDTO();
        voice.setSpeakerId(speakerId);
        voice.setName(StringUtils.firstNonBlank(
                text(status, "Alias", "alias", "SpeakerName", "speaker_name", "Name", "name"),
                speakerId));
        voice.setState(StringUtils.defaultIfBlank(StringUtils.firstNonBlank(
                detail == null ? null : text(detail, "State", "state"),
                text(status, "State", "state")), "Unknown"));
        voice.setCloneVersion(config.cloneVersion());
        voice.setResourceId(config.resourceId());
        voice.setDemoAudio(StringUtils.firstNonBlank(
                detail == null ? null : text(detail, "DemoAudio", "demo_audio"),
                text(status, "DemoAudio", "demo_audio")));
        voice.setCreateTime(longValue(status, "CreateTime", "create_time"));
        voice.setExpireTime(longValue(status, "ExpireTime", "expire_time"));
        return voice;
    }

    private JsonNode matchingModelDetail(JsonNode details, String resourceId) {
        if (!details.isArray()) {
            return null;
        }
        for (JsonNode detail : details) {
            if (resourceId.equals(text(detail, "ResourceID", "ResourceId", "resource_id"))) {
                return detail;
            }
        }
        return null;
    }

    static String normalizeCloneVersion(String version) {
        String normalized = StringUtils.defaultString(version).trim();
        if ("1".equals(normalized) || "1.0".equals(normalized)) {
            return "1.0";
        }
        if ("2".equals(normalized) || "2.0".equals(normalized)) {
            return "2.0";
        }
        throw new RenException("声音复刻版本只能选择1.0或2.0");
    }

    static String resourceId(String cloneVersion) {
        return "2.0".equals(cloneVersion) ? "seed-icl-2.0" : "seed-icl-1.0";
    }

    private boolean isReady(String state) {
        return "success".equalsIgnoreCase(state) || "active".equalsIgnoreCase(state);
    }

    private byte[] signingKey(String secret, String shortDate) throws Exception {
        byte[] dateKey = hmac(secret.getBytes(StandardCharsets.UTF_8), shortDate);
        byte[] regionKey = hmac(dateKey, REGION);
        byte[] serviceKey = hmac(regionKey, SERVICE);
        return hmac(serviceKey, "request");
    }

    private static byte[] hmac(byte[] key, String data) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(key, "HmacSHA256"));
        return mac.doFinal(data.getBytes(StandardCharsets.UTF_8));
    }

    private static String sha256Hex(byte[] data) throws Exception {
        return hex(MessageDigest.getInstance("SHA-256").digest(data));
    }

    private static String hex(byte[] data) {
        StringBuilder result = new StringBuilder(data.length * 2);
        for (byte value : data) {
            result.append(String.format(Locale.ROOT, "%02x", value & 0xff));
        }
        return result.toString();
    }

    private static String text(JsonNode node, String... names) {
        for (String name : names) {
            JsonNode value = node.path(name);
            if (value.isTextual() || value.isNumber() || value.isBoolean()) {
                String text = value.asText();
                if (StringUtils.isNotBlank(text)) {
                    return text;
                }
            }
        }
        return null;
    }

    private static Long longValue(JsonNode node, String... names) {
        for (String name : names) {
            JsonNode value = node.path(name);
            if (value.canConvertToLong()) {
                return value.asLong();
            }
        }
        return null;
    }

    private static String excerpt(String body) {
        String value = StringUtils.defaultString(body).replaceAll("[\\r\\n\\t]+", " ").trim();
        return StringUtils.abbreviate(value, 500);
    }

    private static String safeMessage(Exception e) {
        return StringUtils.abbreviate(StringUtils.defaultIfBlank(e.getMessage(), e.getClass().getSimpleName()), 300);
    }

    private record ResolvedConfig(String modelId, String cloneVersion, String resourceId,
            String appId, String accessKeyId, String accessKeySecret) {
    }
}
