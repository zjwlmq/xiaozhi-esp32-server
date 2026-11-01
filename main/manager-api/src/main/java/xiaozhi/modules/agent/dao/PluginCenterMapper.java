package xiaozhi.modules.agent.dao;

import org.apache.ibatis.annotations.*;

@Mapper
public interface PluginCenterMapper {
    @Select("SELECT config_json FROM ai_agent_extension_config WHERE agent_id=#{agentId}")
    String loadConfig(@Param("agentId") String agentId);

    @Select("SELECT runtime_status FROM ai_agent_extension_config WHERE agent_id=#{agentId}")
    String loadStatus(@Param("agentId") String agentId);

    @Insert("INSERT INTO ai_agent_extension_config(agent_id,config_json,updated_at) VALUES (#{agentId},#{json},NOW()) " +
            "ON DUPLICATE KEY UPDATE config_json=VALUES(config_json),updated_at=NOW()")
    void saveConfig(@Param("agentId") String agentId, @Param("json") String json);

    @Update("UPDATE ai_agent_extension_config SET runtime_status=#{json} WHERE agent_id=#{agentId}")
    void saveStatus(@Param("agentId") String agentId, @Param("json") String json);
}
