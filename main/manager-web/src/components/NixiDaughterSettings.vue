<template>
  <el-card v-if="state" class="nixi-daughter-card" shadow="never">
    <div class="daughter-header">
      <div>
        <strong>《逆袭》女儿设定</strong>
        <span class="mode-tag">{{ modeLabel }}</span>
      </div>
      <el-switch
        v-model="enabled"
        active-text="启用女儿身份"
        @change="emitPrompt"
      />
    </div>

    <el-alert
      v-if="state.error"
      :title="state.error"
      type="error"
      :closable="false"
      show-icon
    />

    <div v-if="enabled" class="daughter-fields">
      <div class="daughter-grid three-columns">
        <label>
          <span>姓名或昵称</span>
          <el-input v-model="profile.name" maxlength="24" @input="emitPrompt" />
        </label>
        <label>
          <span>年龄阶段</span>
          <el-select v-model="profile.age_stage" @change="emitPrompt">
            <el-option label="儿童" value="child" />
            <el-option label="青少年" value="teen" />
            <el-option label="成年" value="adult" />
          </el-select>
        </label>
        <label>
          <span>家庭来源</span>
          <el-select v-model="profile.origin" @change="emitPrompt">
            <el-option label="不说明" value="unspecified" />
            <el-option label="共同收养" value="adopted" />
            <el-option label="共同抚养" value="co_parented" />
          </el-select>
        </label>
      </div>

      <div class="daughter-grid two-columns">
        <label><span>女儿称呼吴所畏</span><el-input v-model="profile.calls_wu" maxlength="24" @input="emitPrompt" /></label>
        <label><span>女儿称呼池骋</span><el-input v-model="profile.calls_chi" maxlength="24" @input="emitPrompt" /></label>
        <label><span>吴所畏称呼女儿</span><el-input v-model="profile.wu_calls" maxlength="24" @input="emitPrompt" /></label>
        <label><span>池骋称呼女儿</span><el-input v-model="profile.chi_calls" maxlength="24" @input="emitPrompt" /></label>
      </div>

      <label class="full-field">
        <span>吴所畏对女儿的相处方式</span>
        <el-input v-model="profile.wu_style" maxlength="120" show-word-limit @input="emitPrompt" />
      </label>
      <label class="full-field">
        <span>池骋对女儿的相处方式</span>
        <el-input v-model="profile.chi_style" maxlength="120" show-word-limit @input="emitPrompt" />
      </label>
      <label class="full-field">
        <span>家庭互动规则</span>
        <el-input
          v-model="profile.family_rules"
          type="textarea"
          :rows="2"
          maxlength="240"
          show-word-limit
          @input="emitPrompt"
        />
      </label>
      <p class="daughter-note">
        这些内容属于当前角色配置的 session fiction，不会改写小说或剧版原著事实。
      </p>
    </div>
  </el-card>
</template>

<script>
import {
  DEFAULT_DAUGHTER_PROFILE,
  getDaughterEditorState,
  updateDaughterSettings
} from "@/utils/nixiDaughterProfile";

export default {
  name: "NixiDaughterSettings",
  props: {
    value: { type: String, default: "" }
  },
  data() {
    return {
      state: null,
      enabled: false,
      profile: { ...DEFAULT_DAUGHTER_PROFILE },
      lastEmittedPrompt: ""
    };
  },
  computed: {
    modeLabel() {
      if (!this.state) return "";
      return { wu: "吴所畏单人", chi: "池骋单人", duo: "双人" }[this.state.mode] || this.state.mode;
    }
  },
  watch: {
    value: {
      immediate: true,
      handler(prompt) {
        if (prompt === this.lastEmittedPrompt) {
          this.lastEmittedPrompt = "";
          return;
        }
        const state = getDaughterEditorState(prompt);
        this.state = state;
        if (state) {
          this.enabled = state.enabled;
          this.profile = { ...state.profile };
        }
      }
    }
  },
  methods: {
    emitPrompt() {
      if (!this.state || this.state.error) return;
      const nextPrompt = updateDaughterSettings(this.value, this.enabled, this.profile);
      if (nextPrompt !== this.value) {
        this.lastEmittedPrompt = nextPrompt;
        this.$emit("input", nextPrompt);
      }
    }
  }
};
</script>

<style scoped>
.nixi-daughter-card {
  margin: -4px 0 18px 72px;
  border-color: #c8d7ff;
  background: #f8faff;
}
.daughter-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.mode-tag {
  margin-left: 10px;
  padding: 2px 8px;
  border-radius: 10px;
  color: #4968d9;
  background: #e7edff;
  font-size: 12px;
}
.daughter-fields {
  margin-top: 16px;
}
.daughter-grid {
  display: grid;
  gap: 12px;
  margin-bottom: 12px;
}
.three-columns { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.two-columns { grid-template-columns: repeat(2, minmax(0, 1fr)); }
label > span {
  display: block;
  margin-bottom: 6px;
  color: #606266;
  font-size: 13px;
}
.full-field {
  display: block;
  margin-top: 12px;
}
.daughter-note {
  margin: 12px 0 0;
  color: #8490a8;
  font-size: 12px;
}
@media (max-width: 900px) {
  .nixi-daughter-card { margin-left: 0; }
  .three-columns, .two-columns { grid-template-columns: 1fr; }
}
</style>
