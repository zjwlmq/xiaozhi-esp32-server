package xiaozhi.modules.model.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import cn.hutool.json.JSONObject;
import xiaozhi.modules.model.dao.ModelConfigDao;
import xiaozhi.modules.model.dto.UpstreamModelListDTO;
import xiaozhi.modules.model.dto.UpstreamModelProbeRequestDTO;
import xiaozhi.modules.model.dto.UpstreamModelTestDTO;
import xiaozhi.modules.model.entity.ModelConfigEntity;

class ModelUpstreamProbeServiceTest {

    private HttpServer server;
    private String baseUrl;
    private ModelConfigDao modelConfigDao;
    private ModelUpstreamProbeService service;

    @BeforeEach
    void setUp() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.start();
        baseUrl = "http://127.0.0.1:" + server.getAddress().getPort();
        modelConfigDao = mock(ModelConfigDao.class);
        service = new ModelUpstreamProbeService(modelConfigDao, new ObjectMapper());
    }

    @AfterEach
    void tearDown() {
        server.stop(0);
    }

    @Test
    void fetchesAnthropicModelsWithConfiguredHeaders() {
        AtomicReference<String> userAgent = new AtomicReference<>();
        AtomicReference<String> apiKey = new AtomicReference<>();
        server.createContext("/v1/models", exchange -> {
            userAgent.set(exchange.getRequestHeaders().getFirst("User-Agent"));
            apiKey.set(exchange.getRequestHeaders().getFirst("x-api-key"));
            respond(exchange, 200, "{\"data\":[{\"id\":\"claude-opus-5\",\"display_name\":\"Claude Opus 5\"},{\"id\":\"claude-sonnet-5\"}]}");
        });

        UpstreamModelListDTO result = service.fetchModels(request(config(
                "anthropic_messages", "test-secret", "claude-cli/2.1.233 (external, cli)")));

        assertEquals(2, result.getModels().size());
        assertEquals("claude-opus-5", result.getModels().get(0).getId());
        assertEquals("claude-cli/2.1.233 (external, cli)", userAgent.get());
        assertEquals("test-secret", apiKey.get());
        assertEquals(200, result.getUpstreamStatus());
    }

    @Test
    void testsAnthropicMessageAndExtractsText() {
        AtomicReference<String> requestBody = new AtomicReference<>();
        server.createContext("/v1/messages", exchange -> {
            requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            respond(exchange, 200, "{\"content\":[{\"type\":\"text\",\"text\":\"hi from upstream\"}]}");
        });
        UpstreamModelProbeRequestDTO request = request(config("anthropic_messages", "test-secret", null));
        request.setModelName("claude-opus-5");
        request.setPrompt("hi");

        UpstreamModelTestDTO result = service.testConnection(request);

        assertTrue(result.isSuccess());
        assertEquals("hi from upstream", result.getResponse());
        assertTrue(requestBody.get().contains("\"model\":\"claude-opus-5\""));
        assertTrue(requestBody.get().contains("\"content\":\"hi\""));
    }

    @Test
    void restoresSavedSecretWhenBrowserSendsMaskedValue() {
        AtomicReference<String> apiKey = new AtomicReference<>();
        server.createContext("/v1/models", exchange -> {
            apiKey.set(exchange.getRequestHeaders().getFirst("x-api-key"));
            respond(exchange, 200, "{\"data\":[{\"id\":\"claude-opus-5\"}]}");
        });
        ModelConfigEntity saved = new ModelConfigEntity();
        saved.setConfigJson(config("anthropic_messages", "real-saved-secret", null));
        when(modelConfigDao.selectById("LLM_saved")).thenReturn(saved);

        JSONObject masked = config("anthropic_messages", "real********cret", null);
        UpstreamModelProbeRequestDTO request = request(masked);
        request.setModelId("LLM_saved");

        service.fetchModels(request);

        assertEquals("real-saved-secret", apiKey.get());
    }

    @Test
    void normalizesRootAndCompletedEndpointUrls() {
        assertEquals("https://example.com/v1/models",
                ModelUpstreamProbeService.modelsEndpoint("https://example.com", "anthropic_messages").toString());
        assertEquals("https://example.com/v1/models",
                ModelUpstreamProbeService.modelsEndpoint("https://example.com/v1/messages", "anthropic_messages").toString());
        assertEquals("https://example.com/v1/chat/completions",
                ModelUpstreamProbeService.messagesEndpoint("https://example.com/v1", "openai").toString());
    }

    private UpstreamModelProbeRequestDTO request(JSONObject config) {
        UpstreamModelProbeRequestDTO request = new UpstreamModelProbeRequestDTO();
        request.setConfigJson(config);
        return request;
    }

    private JSONObject config(String type, String apiKey, String userAgent) {
        JSONObject config = new JSONObject();
        config.set("type", type);
        config.set("base_url", baseUrl);
        config.set("api_key", apiKey);
        config.set("auth_type", "x-api-key");
        config.set("anthropic_version", "2023-06-01");
        if (userAgent != null) {
            config.set("user_agent", userAgent);
        }
        return config;
    }

    private static void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
