package xiaozhi.modules.agent.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import xiaozhi.common.exception.RenException;
import static org.junit.jupiter.api.Assertions.*;

class PluginCatalogTest {
    private final PluginCatalog catalog = new PluginCatalog();
    private final ObjectMapper json = new ObjectMapper();

    @Test void rejectsUnknownPluginAndFields() throws Exception {
        assertThrows(RenException.class, () -> catalog.manifest("unknown"));
        var patch=json.readTree("{\"settings\":{\"command\":\"anything\"}}");
        assertThrows(RenException.class, () -> catalog.merge("image-generation",null,patch));
    }

    @Test void validatesValuesRatherThanCoercingThem() throws Exception {
        for (String value : new String[]{"true", "0", "100000", "\"120\""}) {
            var patch=json.readTree("{\"settings\":{\"interval_minutes\":" + value + "}}");
            assertThrows(RenException.class, () -> catalog.merge("proactive-messaging",null,patch));
        }
        var patch=json.readTree("{\"enabled\":\"false\"}");
        assertThrows(RenException.class, () -> catalog.merge("time-awareness",null,patch));
    }

    @Test void rejectsAmbiguousCalendarAndEmbeddedCredentials() throws Exception {
        var calendar=json.readTree("{\"settings\":{\"calendar\":[{\"date\":\"2026-02-30\",\"is_day_off\":true}]}}");
        assertThrows(RenException.class, () -> catalog.merge("holiday-awareness",null,calendar));
        var url=json.readTree("{\"settings\":{\"endpoint\":\"https://user:secret@example.test/images\"}}");
        assertThrows(RenException.class, () -> catalog.merge("image-generation",null,url));
    }

    @Test void defaultsAreIsolatedAndSecretsNeverRoundTripToTheBrowser() throws Exception {
        var state=catalog.merge("image-generation",null,json.readTree("{\"settings\":{\"api_key\":\"test-private-key\",\"model\":\"test\"}}"));
        var safe=catalog.redact("image-generation",state);
        assertFalse(safe.toString().contains("test-private-key"));
        assertEquals("api_key",safe.path("configured_secrets").get(0).asText());
        assertEquals("test-private-key",state.path("settings").path("api_key").asText());
        var unchanged=catalog.merge("image-generation",state,json.readTree("{\"enabled\":true}"));
        assertEquals("test-private-key",unchanged.path("settings").path("api_key").asText());
        var cleared=catalog.merge("image-generation",state,json.readTree("{\"settings\":{\"api_key\":null}}"));
        assertEquals("",cleared.path("settings").path("api_key").asText());
        assertEquals("",catalog.defaults("image-generation").path("model").asText());
    }
}
