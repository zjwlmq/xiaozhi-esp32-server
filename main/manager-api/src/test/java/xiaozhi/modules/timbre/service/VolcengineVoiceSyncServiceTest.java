package xiaozhi.modules.timbre.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import cn.hutool.json.JSONObject;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.model.dao.ModelConfigDao;
import xiaozhi.modules.model.entity.ModelConfigEntity;
import xiaozhi.modules.timbre.dto.TimbreDataDTO;
import xiaozhi.modules.timbre.dto.VolcengineUpstreamVoiceListDTO;
import xiaozhi.modules.timbre.dto.VolcengineVoiceImportRequestDTO;
import xiaozhi.modules.timbre.dto.VolcengineVoiceImportResultDTO;
import xiaozhi.modules.timbre.dto.VolcengineVoiceSyncRequestDTO;

class VolcengineVoiceSyncServiceTest {

    private HttpServer server;
    private ModelConfigDao modelConfigDao;
    private TimbreService timbreService;
    private VolcengineVoiceSyncService service;
    private AtomicReference<String> requestBody;
    private AtomicReference<String> authorization;

    @BeforeEach
    void setUp() throws IOException {
        requestBody = new AtomicReference<>();
        authorization = new AtomicReference<>();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            authorization.set(exchange.getRequestHeaders().getFirst("Authorization"));
            respond(exchange, 200, upstreamResponse());
        });
        server.start();

        modelConfigDao = mock(ModelConfigDao.class);
        timbreService = mock(TimbreService.class);
        when(modelConfigDao.selectById("TTS_TEST")).thenReturn(model("test-ak", "test-sk"));
        service = new VolcengineVoiceSyncService(modelConfigDao, timbreService, new ObjectMapper(),
                HttpClient.newHttpClient(),
                URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/"),
                Clock.fixed(Instant.parse("2026-08-20T10:15:30Z"), ZoneOffset.UTC));
    }

    @AfterEach
    void tearDown() {
        server.stop(0);
    }

    @Test
    void fetchesOnlySelectedCloneVersionAndSignsOnServer() {
        VolcengineVoiceSyncRequestDTO request = request("2.0");

        VolcengineUpstreamVoiceListDTO result = service.fetchVoices(request);

        assertEquals("seed-icl-2.0", result.getResourceId());
        assertEquals(1, result.getVoices().size());
        assertEquals("S_dual", result.getVoices().get(0).getSpeakerId());
        assertEquals("https://example.test/2.wav", result.getVoices().get(0).getDemoAudio());
        assertTrue(requestBody.get().contains("\"AppID\":\"test-app\""));
        assertTrue(authorization.get().contains("Credential=test-ak/20260820/cn-north-1/speech_saas_prod/request"));
    }

    @Test
    void importsAuthoritativeUpstreamDataWithVersionResourceId() {
        VolcengineVoiceImportRequestDTO request = new VolcengineVoiceImportRequestDTO();
        request.setTtsModelId("TTS_TEST");
        request.setCloneVersion("2.0");
        request.setSpeakerIds(List.of("S_dual"));

        VolcengineVoiceImportResultDTO result = service.importVoices(request);

        assertEquals(1, result.getImportedCount());
        assertEquals(0, result.getSkippedCount());
        ArgumentCaptor<TimbreDataDTO> captor = ArgumentCaptor.forClass(TimbreDataDTO.class);
        verify(timbreService).save(captor.capture());
        assertEquals("S_dual", captor.getValue().getTtsVoice());
        assertEquals("Dual voice", captor.getValue().getName());
        assertEquals("seed-icl-2.0", captor.getValue().getUpstreamResourceId());
        assertEquals("https://example.test/2.wav", captor.getValue().getVoiceDemo());
    }

    @Test
    void rejectsMissingOpenApiCredentialsBeforeNetworkCall() {
        when(modelConfigDao.selectById("TTS_TEST")).thenReturn(model("", ""));

        RenException exception = assertThrows(RenException.class, () -> service.fetchVoices(request("1.0")));

        assertTrue(exception.getMessage().contains("Access Key"));
    }

    @Test
    void rejectsUnknownCloneVersion() {
        assertThrows(RenException.class, () -> service.fetchVoices(request("3.0")));
    }

    private VolcengineVoiceSyncRequestDTO request(String version) {
        VolcengineVoiceSyncRequestDTO request = new VolcengineVoiceSyncRequestDTO();
        request.setTtsModelId("TTS_TEST");
        request.setCloneVersion(version);
        return request;
    }

    private ModelConfigEntity model(String accessKeyId, String accessKeySecret) {
        JSONObject config = new JSONObject();
        config.set("type", "huoshan_double_stream");
        config.set("appid", "test-app");
        config.set("access_key_id", accessKeyId);
        config.set("access_key_secret", accessKeySecret);
        ModelConfigEntity model = new ModelConfigEntity();
        model.setId("TTS_TEST");
        model.setConfigJson(config);
        return model;
    }

    private static String upstreamResponse() {
        return """
                {"ResponseMetadata":{"RequestId":"test"},"Result":{"Statuses":[
                  {"SpeakerID":"S_dual","Alias":"Dual voice","State":"Success","CreateTime":20,
                   "ModelTypeDetails":[
                     {"ResourceID":"seed-icl-1.0","DemoAudio":"https://example.test/1.wav"},
                     {"ResourceID":"seed-icl-2.0","DemoAudio":"https://example.test/2.wav"}]},
                  {"SpeakerID":"S_only1","Alias":"Only one","State":"Success","CreateTime":10,
                   "ModelTypeDetails":[{"ResourceID":"seed-icl-1.0"}]}
                ]}}
                """;
    }

    private static void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
