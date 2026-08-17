package xiaozhi.modules.model.service;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import cn.hutool.json.JSONObject;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.utils.SensitiveDataUtils;
import xiaozhi.modules.model.dao.ModelConfigDao;
import xiaozhi.modules.model.dto.UpstreamModelInfoDTO;
import xiaozhi.modules.model.dto.UpstreamModelListDTO;
import xiaozhi.modules.model.dto.UpstreamModelProbeRequestDTO;
import xiaozhi.modules.model.dto.UpstreamModelTestDTO;
import xiaozhi.modules.model.entity.ModelConfigEntity;

/**
 * 在管理端后端代发上游模型查询和最小聊天测试。
 * 密钥始终留在后端，返回结果不包含请求头或完整上游响应。
 */
@Service
public class ModelUpstreamProbeService {

    private static final int MAX_RESPONSE_CHARS = 1_000_000;
    private static final int MAX_RESULT_CHARS = 4_000;
    private static final Duration CONNECT_TIMEOUT = Duration.ofSeconds(10);
    private static final Duration DEFAULT_REQUEST_TIMEOUT = Duration.ofSeconds(30);

    private final ModelConfigDao modelConfigDao;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    public ModelUpstreamProbeService(ModelConfigDao modelConfigDao, ObjectMapper objectMapper) {
        this(modelConfigDao, objectMapper, HttpClient.newBuilder()
                .connectTimeout(CONNECT_TIMEOUT)
                .followRedirects(HttpClient.Redirect.NEVER)
                .build());
    }

    ModelUpstreamProbeService(ModelConfigDao modelConfigDao, ObjectMapper objectMapper, HttpClient httpClient) {
        this.modelConfigDao = modelConfigDao;
        this.objectMapper = objectMapper;
        this.httpClient = httpClient;
    }

    public UpstreamModelListDTO fetchModels(UpstreamModelProbeRequestDTO request) {
        JSONObject config = resolveConfig(request);
        String providerType = providerType(config);
        URI endpoint = modelsEndpoint(requireBaseUrl(config), providerType);
        long started = System.nanoTime();
        HttpResponse<String> response = send(HttpRequest.newBuilder(endpoint)
                .timeout(requestTimeout(config))
                .GET(), config, providerType, false);
        long latencyMs = elapsedMillis(started);
        requireSuccess(response, "获取模型列表");

        List<UpstreamModelInfoDTO> models = parseModels(response.body());
        if (models.isEmpty()) {
            throw new RenException("上游返回成功，但没有解析到模型ID");
        }
        UpstreamModelListDTO result = new UpstreamModelListDTO();
        result.setModels(models);
        result.setLatencyMs(latencyMs);
        result.setUpstreamStatus(response.statusCode());
        result.setEndpoint(safeEndpoint(endpoint));
        return result;
    }

    public UpstreamModelTestDTO testConnection(UpstreamModelProbeRequestDTO request) {
        JSONObject config = resolveConfig(request);
        String providerType = providerType(config);
        String model = StringUtils.firstNonBlank(request == null ? null : request.getModelName(),
                config.getStr("model_name"));
        if (StringUtils.isBlank(model)) {
            throw new RenException("请先选择或填写上游模型名称");
        }
        String prompt = StringUtils.firstNonBlank(request == null ? null : request.getPrompt(), "hi");
        if (prompt.length() > 2_000) {
            throw new RenException("测试消息不能超过2000个字符");
        }

        URI endpoint = messagesEndpoint(requireBaseUrl(config), providerType);
        String body = buildTestBody(providerType, model, prompt);
        long started = System.nanoTime();
        HttpResponse<String> response = send(HttpRequest.newBuilder(endpoint)
                .timeout(requestTimeout(config))
                .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8)), config, providerType, true);
        long latencyMs = elapsedMillis(started);
        requireSuccess(response, "测试模型连接");

        UpstreamModelTestDTO result = new UpstreamModelTestDTO();
        result.setSuccess(true);
        result.setModel(model);
        result.setResponse(extractText(response.body(), providerType));
        result.setRequestId(firstHeader(response, "request-id", "x-request-id", "cf-ray"));
        result.setLatencyMs(latencyMs);
        result.setUpstreamStatus(response.statusCode());
        result.setEndpoint(safeEndpoint(endpoint));
        return result;
    }

    private JSONObject resolveConfig(UpstreamModelProbeRequestDTO request) {
        if (request == null) {
            throw new RenException("测试参数不能为空");
        }
        JSONObject resolved = new JSONObject();
        if (StringUtils.isNotBlank(request.getModelId())) {
            ModelConfigEntity saved = modelConfigDao.selectById(request.getModelId());
            if (saved == null) {
                throw new RenException("模型配置不存在");
            }
            if (saved.getConfigJson() != null) {
                resolved.putAll(saved.getConfigJson());
            }
        }
        JSONObject incoming = request.getConfigJson();
        if (incoming != null) {
            for (String key : incoming.keySet()) {
                Object value = incoming.get(key);
                if (SensitiveDataUtils.isSensitiveField(key) && value instanceof String stringValue
                        && (StringUtils.isBlank(stringValue) || SensitiveDataUtils.isMaskedValue(stringValue))) {
                    continue;
                }
                resolved.set(key, value);
            }
        }
        return resolved;
    }

    private String providerType(JSONObject config) {
        String type = StringUtils.defaultString(config.getStr("type")).toLowerCase(Locale.ROOT);
        if (!"anthropic_messages".equals(type) && !"openai".equals(type)) {
            throw new RenException("当前仅支持 Anthropic Messages 和 OpenAI 兼容模型的上游检测");
        }
        return type;
    }

    private String requireBaseUrl(JSONObject config) {
        String baseUrl = StringUtils.trim(config.getStr("base_url"));
        if (StringUtils.isBlank(baseUrl)) {
            throw new RenException("基础URL不能为空");
        }
        return baseUrl;
    }

    static URI modelsEndpoint(String baseUrl, String providerType) {
        URI base = validatedBaseUri(baseUrl);
        String path = trimTrailingSlash(StringUtils.defaultString(base.getPath()));
        if (path.endsWith("/chat/completions")) {
            path = path.substring(0, path.length() - "/chat/completions".length());
        } else if (path.endsWith("/messages")) {
            path = path.substring(0, path.length() - "/messages".length());
        }
        if (path.isEmpty()) {
            path = "/v1";
        }
        return replacePath(base, path + "/models");
    }

    static URI messagesEndpoint(String baseUrl, String providerType) {
        URI base = validatedBaseUri(baseUrl);
        String path = trimTrailingSlash(StringUtils.defaultString(base.getPath()));
        if ("anthropic_messages".equals(providerType)) {
            if (path.endsWith("/messages")) {
                return replacePath(base, path);
            }
            if (path.isEmpty()) {
                path = "/v1";
            }
            return replacePath(base, path + "/messages");
        }
        if (path.endsWith("/chat/completions")) {
            return replacePath(base, path);
        }
        if (path.isEmpty()) {
            path = "/v1";
        }
        return replacePath(base, path + "/chat/completions");
    }

    private static URI validatedBaseUri(String baseUrl) {
        try {
            URI uri = URI.create(baseUrl.trim());
            if (!("http".equalsIgnoreCase(uri.getScheme()) || "https".equalsIgnoreCase(uri.getScheme()))
                    || StringUtils.isBlank(uri.getHost()) || uri.getUserInfo() != null) {
                throw new IllegalArgumentException();
            }
            if (uri.getRawQuery() != null || uri.getRawFragment() != null) {
                throw new IllegalArgumentException();
            }
            return uri;
        } catch (IllegalArgumentException e) {
            throw new RenException("基础URL格式无效，仅支持不带用户信息、查询参数或片段的 HTTP(S) 地址");
        }
    }

    private static URI replacePath(URI base, String path) {
        try {
            return new URI(base.getScheme(), null, base.getHost(), base.getPort(), path, null, null);
        } catch (Exception e) {
            throw new RenException("无法生成上游请求地址");
        }
    }

    private HttpResponse<String> send(HttpRequest.Builder builder, JSONObject config, String providerType,
            boolean hasBody) {
        builder.header("accept", "application/json");
        if (hasBody) {
            builder.header("content-type", "application/json");
        }
        String apiKey = StringUtils.trim(config.getStr("api_key"));
        if (StringUtils.isBlank(apiKey)) {
            throw new RenException("API密钥不能为空");
        }
        rejectHeaderInjection(apiKey, "API密钥");
        if ("anthropic_messages".equals(providerType)) {
            String authType = StringUtils.defaultIfBlank(config.getStr("auth_type"), "x-api-key");
            if ("bearer".equalsIgnoreCase(authType)) {
                builder.header("authorization", "Bearer " + apiKey);
            } else {
                builder.header("x-api-key", apiKey);
            }
            addOptionalHeader(builder, "anthropic-version",
                    StringUtils.defaultIfBlank(config.getStr("anthropic_version"), "2023-06-01"));
            addOptionalHeader(builder, "anthropic-beta", config.getStr("anthropic_beta"));
        } else {
            builder.header("authorization", "Bearer " + apiKey);
        }
        addOptionalHeader(builder, "user-agent", config.getStr("user_agent"));

        try {
            HttpResponse<String> response = httpClient.send(builder.build(),
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.body() != null && response.body().length() > MAX_RESPONSE_CHARS) {
                throw new RenException("上游响应过大，已停止处理");
            }
            return response;
        } catch (HttpTimeoutException e) {
            throw new RenException("上游请求超时，请检查地址、网络或超时配置");
        } catch (IOException e) {
            throw new RenException("无法连接上游：" + safeExceptionMessage(e));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new RenException("上游请求被中断");
        }
    }

    private void addOptionalHeader(HttpRequest.Builder builder, String name, String value) {
        if (StringUtils.isNotBlank(value)) {
            rejectHeaderInjection(value, name);
            builder.header(name, value.trim());
        }
    }

    private void rejectHeaderInjection(String value, String label) {
        if (value.indexOf('\r') >= 0 || value.indexOf('\n') >= 0) {
            throw new RenException(label + "包含非法换行符");
        }
    }

    private Duration requestTimeout(JSONObject config) {
        int seconds = 30;
        try {
            Object raw = config.get("timeout");
            if (raw != null) {
                seconds = (int) Math.ceil(Double.parseDouble(raw.toString()));
            }
        } catch (NumberFormatException ignored) {
            seconds = 30;
        }
        if (seconds <= 0) {
            return DEFAULT_REQUEST_TIMEOUT;
        }
        return Duration.ofSeconds(Math.min(seconds, 90));
    }

    private String buildTestBody(String providerType, String model, String prompt) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("model", model);
        payload.put("messages", List.of(Map.of("role", "user", "content", prompt)));
        payload.put("stream", false);
        if ("anthropic_messages".equals(providerType)) {
            payload.put("max_tokens", 64);
        } else {
            payload.put("max_tokens", 64);
        }
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (JsonProcessingException e) {
            throw new RenException("无法生成测试请求");
        }
    }

    private List<UpstreamModelInfoDTO> parseModels(String body) {
        try {
            JsonNode root = objectMapper.readTree(body);
            JsonNode items = root.isArray() ? root : firstArray(root, "data", "models");
            if (items == null || !items.isArray()) {
                return List.of();
            }
            Map<String, UpstreamModelInfoDTO> unique = new LinkedHashMap<>();
            for (JsonNode item : items) {
                String id;
                String name;
                if (item.isTextual()) {
                    id = item.asText();
                    name = id;
                } else {
                    id = firstText(item, "id", "name", "model");
                    name = firstText(item, "display_name", "name", "id", "model");
                }
                if (StringUtils.isNotBlank(id)) {
                    unique.putIfAbsent(id, new UpstreamModelInfoDTO(id, StringUtils.defaultIfBlank(name, id)));
                }
            }
            List<UpstreamModelInfoDTO> result = new ArrayList<>(unique.values());
            result.sort(Comparator.comparing(UpstreamModelInfoDTO::getId, String.CASE_INSENSITIVE_ORDER));
            return result;
        } catch (JsonProcessingException e) {
            throw new RenException("上游模型列表不是可识别的JSON：" + responseExcerpt(body));
        }
    }

    private String extractText(String body, String providerType) {
        try {
            JsonNode root = objectMapper.readTree(body);
            if ("anthropic_messages".equals(providerType)) {
                JsonNode content = root.path("content");
                if (content.isArray()) {
                    List<String> parts = new ArrayList<>();
                    for (JsonNode part : content) {
                        String text = part.path("text").asText("");
                        if (StringUtils.isNotBlank(text)) {
                            parts.add(text);
                        }
                    }
                    if (!parts.isEmpty()) {
                        return abbreviate(String.join("\n", parts));
                    }
                }
            } else {
                JsonNode content = root.path("choices").path(0).path("message").path("content");
                if (content.isTextual()) {
                    return abbreviate(content.asText());
                }
            }
            return abbreviate(responseExcerpt(body));
        } catch (JsonProcessingException e) {
            return abbreviate(responseExcerpt(body));
        }
    }

    private void requireSuccess(HttpResponse<String> response, String action) {
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new RenException(action + "失败：上游 HTTP " + response.statusCode() + " - "
                    + responseExcerpt(response.body()));
        }
    }

    private static JsonNode firstArray(JsonNode root, String... names) {
        for (String name : names) {
            JsonNode node = root.path(name);
            if (node.isArray()) {
                return node;
            }
        }
        return null;
    }

    private static String firstText(JsonNode node, String... names) {
        for (String name : names) {
            JsonNode child = node.path(name);
            if (child.isValueNode() && StringUtils.isNotBlank(child.asText())) {
                return child.asText();
            }
        }
        return null;
    }

    private static String firstHeader(HttpResponse<?> response, String... names) {
        for (String name : names) {
            String value = response.headers().firstValue(name).orElse(null);
            if (StringUtils.isNotBlank(value)) {
                return abbreviate(value);
            }
        }
        return null;
    }

    private static String responseExcerpt(String body) {
        if (body == null) {
            return "(空响应)";
        }
        String cleaned = body.replaceAll("(?is)<script.*?</script>", " ")
                .replaceAll("(?is)<style.*?</style>", " ")
                .replaceAll("(?s)<[^>]+>", " ")
                .replaceAll("\\s+", " ")
                .trim();
        return abbreviate(cleaned);
    }

    private static String abbreviate(String value) {
        if (value == null) {
            return "";
        }
        return value.length() <= MAX_RESULT_CHARS ? value : value.substring(0, MAX_RESULT_CHARS) + "…";
    }

    private static String safeExceptionMessage(Exception e) {
        String message = StringUtils.defaultIfBlank(e.getMessage(), e.getClass().getSimpleName());
        return abbreviate(message.replaceAll("[\\r\\n]+", " "));
    }

    private static String safeEndpoint(URI uri) {
        return uri.getScheme() + "://" + uri.getAuthority() + uri.getPath();
    }

    private static String trimTrailingSlash(String path) {
        while (path.endsWith("/") && path.length() > 1) {
            path = path.substring(0, path.length() - 1);
        }
        return "/".equals(path) ? "" : path;
    }

    private static long elapsedMillis(long startedNanos) {
        return Duration.ofNanos(System.nanoTime() - startedNanos).toMillis();
    }
}
