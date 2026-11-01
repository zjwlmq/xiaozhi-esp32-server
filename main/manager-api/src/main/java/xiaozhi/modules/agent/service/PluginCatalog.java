package xiaozhi.modules.agent.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;
import xiaozhi.common.exception.RenException;
import java.io.IOException;
import java.net.URI;
import java.time.LocalDate;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;

@Component
public class PluginCatalog {
    private final ObjectMapper json = new ObjectMapper();
    private final JsonNode catalog;

    public PluginCatalog() {
        try (var stream = new ClassPathResource("plugin-center/catalog.json").getInputStream()) {
            catalog = json.readTree(stream);
        } catch (IOException e) { throw new IllegalStateException("插件目录加载失败", e); }
    }

    public JsonNode catalog() { return catalog.deepCopy(); }

    public JsonNode manifest(String id) {
        for (JsonNode item : catalog.path("plugins")) if (item.path("id").asText().equals(id)) return item;
        throw new RenException("未知插件");
    }

    public ObjectNode defaults(String id) {
        ObjectNode settings = json.createObjectNode();
        for (JsonNode field : manifest(id).path("fields")) settings.set(field.path("key").asText(), field.path("default").deepCopy());
        return settings;
    }

    public ObjectNode defaultState(String id) {
        ObjectNode value = json.createObjectNode().put("enabled", false);
        value.set("settings", defaults(id));
        return value;
    }

    public ObjectNode merge(String id, JsonNode previous, JsonNode patch) {
        if (!patch.isObject()) throw new RenException("插件设置格式无效");
        patch.fieldNames().forEachRemaining(key -> {
            if (!Set.of("enabled", "settings").contains(key)) throw new RenException("未知插件字段");
        });
        ObjectNode result = previous != null && previous.isObject() ? previous.deepCopy() : defaultState(id);
        if (patch.has("enabled")) {
            if (!patch.get("enabled").isBoolean()) throw new RenException("插件开关格式无效");
            result.set("enabled", patch.get("enabled"));
        }
        if (patch.has("settings")) {
            if (!patch.get("settings").isObject()) throw new RenException("插件配置格式无效");
            ObjectNode settings = (ObjectNode) result.get("settings");
            Iterator<String> keys = patch.get("settings").fieldNames();
            while (keys.hasNext()) {
                String key = keys.next();
                JsonNode field = null;
                for (JsonNode candidate : manifest(id).path("fields")) if (candidate.path("key").asText().equals(key)) field = candidate;
                if (field == null) throw new RenException("未知配置字段：" + key);
                JsonNode value = patch.get("settings").get(key);
                if (field.path("type").asText().equals("secret") && value.isNull()) value = json.getNodeFactory().textNode("");
                validate(field, value);
                settings.set(key, value.deepCopy());
            }
        }
        return result;
    }

    private void validate(JsonNode field, JsonNode value) {
        String type = field.path("type").asText();
        String label = field.path("label").asText();
        boolean valid;
        if (type.equals("integer")) {
            valid = value.isIntegralNumber() && value.canConvertToInt()
                    && value.asInt() >= field.path("min").asInt() && value.asInt() <= field.path("max").asInt();
        } else if (type.equals("boolean")) valid = value.isBoolean();
        else if (type.equals("json")) {
            validateCalendar(value);
            return;
        } else {
            valid = value.isTextual() && value.asText().length() <= field.path("maxLength").asInt(2048);
            if (valid && type.equals("select")) {
                valid = false;
                for (JsonNode option : field.path("options")) if (option.equals(value)) valid = true;
            }
            if (valid && type.equals("time")) valid = value.asText().matches("(?:[01]\\d|2[0-3]):[0-5]\\d");
            if (valid && type.equals("url") && !value.asText().isBlank()) {
                try {
                    URI uri = URI.create(value.asText());
                    valid = Set.of("http", "https").contains(uri.getScheme()) && uri.getHost() != null
                            && uri.getUserInfo() == null && uri.getFragment() == null && uri.getQuery() == null;
                } catch (IllegalArgumentException e) { valid = false; }
            }
        }
        if (!valid) throw new RenException(label + "格式或范围无效");
    }

    private void validateCalendar(JsonNode value) {
        if (!value.isArray() || value.size() > 800) throw new RenException("日历应为最多800项的数组");
        Set<String> dates = new HashSet<>();
        for (JsonNode day : value) {
            if (!day.isObject()) throw new RenException("日历项格式无效");
            day.fieldNames().forEachRemaining(key -> {
                if (!Set.of("date", "name", "is_day_off").contains(key)) throw new RenException("未知日历字段");
            });
            try { LocalDate.parse(day.path("date").asText()); }
            catch (RuntimeException e) { throw new RenException("日历日期格式无效"); }
            if (!dates.add(day.path("date").asText()) || !day.path("is_day_off").isBoolean()
                    || (day.has("name") && (!day.get("name").isTextual() || day.get("name").asText().length() > 80)))
                throw new RenException("日历日期重复或安排格式无效");
        }
    }

    public ObjectNode redact(String id, JsonNode state) {
        ObjectNode result = state.deepCopy();
        ObjectNode settings = (ObjectNode) result.get("settings");
        var configured = result.putArray("configured_secrets");
        for (JsonNode field : manifest(id).path("fields")) if (field.path("type").asText().equals("secret")) {
            String key = field.path("key").asText();
            if (!settings.path(key).asText().isBlank()) configured.add(key);
            settings.remove(key);
        }
        return result;
    }
}
