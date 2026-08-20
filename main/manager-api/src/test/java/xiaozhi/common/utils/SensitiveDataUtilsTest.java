package xiaozhi.common.utils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

import cn.hutool.json.JSONObject;

class SensitiveDataUtilsTest {

    @Test
    void masksBothOpenApiCredentialFields() {
        JSONObject input = new JSONObject();
        input.set("access_key_id", "AKLT1234567890");
        input.set("access_key_secret", "secret1234567890");

        JSONObject masked = SensitiveDataUtils.maskSensitiveFields(input);

        assertTrue(masked.getStr("access_key_id").contains("****"));
        assertTrue(masked.getStr("access_key_secret").contains("****"));
        assertEquals("AKLT1234567890", input.getStr("access_key_id"));
    }
}
