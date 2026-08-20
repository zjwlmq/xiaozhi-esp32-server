<template>
  <el-card v-if="active" class="nixi-access-card" shadow="never" v-loading="loading">
    <div class="access-header">
      <div>
        <strong>《逆袭》角色包访问权限</strong>
        <span v-if="policy" class="access-tag">{{ modeLabel }}</span>
      </div>
      <el-button v-if="policy && policy.editable" size="small" type="primary" :loading="saving" @click="savePolicy">
        保存访问策略
      </el-button>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

    <template v-if="policy">
      <el-alert
        v-if="!policy.currentUserAllowed"
        title="当前账号无权使用该角色包；即使手动填写指令，保存和设备运行时也会被拒绝。"
        type="warning"
        :closable="false"
        show-icon
      />

      <div v-if="policy.editable" class="access-fields">
        <el-radio-group v-model="draft.mode">
          <el-radio-button label="owner">仅站长</el-radio-button>
          <el-radio-button label="whitelist">指定账号</el-radio-button>
          <el-radio-button label="public">全站公开</el-radio-button>
        </el-radio-group>

        <div v-if="draft.mode === 'whitelist'" class="whitelist-field">
          <span>允许使用的普通账号</span>
          <el-select
            v-model="draft.whitelistUserIds"
            multiple
            filterable
            collapse-tags
            placeholder="选择账号；站长始终允许"
          >
            <el-option
              v-for="user in selectableUsers"
              :key="user.userId"
              :label="userLabel(user)"
              :value="user.userId"
            />
          </el-select>
        </div>
      </div>

      <p class="access-note">
        {{ policy.editable ? "仅超级管理员可以修改。策略同时作用于网页保存和设备运行，不能靠手写 @rolepack 指令绕过。" : currentStatusText }}
      </p>
    </template>
  </el-card>
</template>

<script>
import Api from "@/apis/api";
import { isNixiRolepackPrompt, NIXI_ACCESS_MODES, normalizeNixiAccessPolicy } from "@/utils/nixiAccessPolicy";

export default {
  name: "NixiAccessPolicySettings",
  props: {
    value: { type: String, default: "" }
  },
  data() {
    return {
      active: false,
      loading: false,
      saving: false,
      loaded: false,
      error: "",
      policy: null,
      draft: { mode: "owner", whitelistUserIds: [] }
    };
  },
  computed: {
    modeLabel() {
      return NIXI_ACCESS_MODES[this.policy.mode] || NIXI_ACCESS_MODES.owner;
    },
    selectableUsers() {
      return (this.policy?.users || []).filter(user => !user.superAdmin && user.status === 1);
    },
    currentStatusText() {
      return this.policy.currentUserAllowed
        ? `当前账号已获授权；访问模式：${this.modeLabel}。`
        : "当前账号未获授权，请联系站点管理员。";
    }
  },
  watch: {
    value: {
      immediate: true,
      handler(prompt) {
        this.active = isNixiRolepackPrompt(prompt);
        if (this.active && !this.loaded && !this.loading) {
          this.loadPolicy();
        }
      }
    }
  },
  methods: {
    applyPolicy(policy) {
      const normalized = normalizeNixiAccessPolicy(policy);
      this.policy = policy;
      this.draft = {
        mode: normalized.mode,
        whitelistUserIds: normalized.whitelistUserIds
      };
      this.loaded = true;
    },
    loadPolicy() {
      this.loading = true;
      this.error = "";
      Api.agent.getNixiAccessPolicy(({ data }) => {
        this.loading = false;
        if (data.code === 0) {
          this.applyPolicy(data.data);
        } else {
          this.error = data.msg || "读取角色包访问策略失败";
        }
      }, () => {
        this.loading = false;
        this.error = "读取角色包访问策略失败";
      });
    },
    savePolicy() {
      if (!this.policy?.editable) return;
      this.saving = true;
      this.error = "";
      Api.agent.updateNixiAccessPolicy({
        mode: this.draft.mode,
        whitelistUserIds: this.draft.mode === "whitelist" ? this.draft.whitelistUserIds : []
      }, ({ data }) => {
        this.saving = false;
        if (data.code === 0) {
          this.applyPolicy(data.data);
          this.$message.success("访问策略已保存");
        } else {
          this.error = data.msg || "保存角色包访问策略失败";
        }
      }, () => {
        this.saving = false;
        this.error = "保存角色包访问策略失败";
      });
    },
    userLabel(user) {
      const name = user.username || `用户 ${user.userId}`;
      return `${name}（ID: ${user.userId}）`;
    }
  }
};
</script>

<style scoped>
.nixi-access-card {
  margin: -4px 0 18px 72px;
  border-color: #d7dce8;
  background: #fbfcff;
}
.access-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.access-tag {
  margin-left: 10px;
  padding: 2px 8px;
  border-radius: 10px;
  color: #4b67cb;
  background: #e9edfb;
  font-size: 12px;
}
.access-fields {
  margin-top: 16px;
}
.whitelist-field {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  margin-top: 14px;
  color: #606266;
  font-size: 13px;
}
.whitelist-field .el-select { width: 100%; }
.access-note {
  margin: 12px 0 0;
  color: #8490a8;
  font-size: 12px;
  line-height: 1.6;
}
@media (max-width: 900px) {
  .nixi-access-card { margin-left: 0; }
  .whitelist-field { grid-template-columns: 1fr; }
}
</style>
