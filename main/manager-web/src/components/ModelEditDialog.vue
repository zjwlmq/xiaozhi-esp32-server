<template>
  <CustomDialog
    :title="$t('modelConfigDialog.editModel')"
    :visible.sync="dialogVisible"
    width="57%"
    class="model-edit-dialog"
    :confirmLoading="saving"
    @confirm="handleSave"
    @close="handleClose"
    @open="handleOpen"
  >
    <div class="dialog-scroll-body">
    <div class="header-row">
      <div class="section-title">{{ $t("modelConfigDialog.modelInfo") }}</div>
      <div class="switch-group">
        <div class="switch-item">
          <span class="switch-label">{{ $t("modelConfigDialog.enable") }}</span>
          <el-switch v-model="form.isEnabled" :active-value="1" :inactive-value="0" class="custom-switch"></el-switch>
        </div>
        <div class="switch-item hidden">
          <span class="switch-label">{{ $t("modelConfigDialog.setDefault") }}</span>
          <el-switch v-model="form.isDefault" :active-value="1" :inactive-value="0" class="custom-switch"></el-switch>
        </div>
      </div>
    </div>

    <div class="section-divider"></div>

    <el-form :model="form" ref="form" label-width="auto" label-position="left">
      <div class="form-row">
        <el-form-item :label="$t('modelConfigDialog.modelName')" prop="name" style="flex: 1">
          <el-input v-model="form.modelName" :placeholder="$t('modelConfigDialog.enterModelName')"></el-input>
        </el-form-item>
        <el-form-item :label="$t('modelConfigDialog.modelCode')" prop="code" style="flex: 1">
          <el-input v-model="form.modelCode" :placeholder="$t('modelConfigDialog.enterModelCode')"></el-input>
        </el-form-item>
      </div>

      <div class="form-row">
        <el-form-item :label="$t('modelConfigDialog.supplier')" prop="supplier" style="flex: 1">
          <el-select v-model="form.configJson.type" :placeholder="$t('modelConfigDialog.selectSupplier')"
            style="width: 100%" @focus="loadProviders" filterable>
            <el-option v-for="item in providers" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="$t('modelConfigDialog.sortOrder')" prop="sort" style="flex: 1">
          <el-input v-model.number="form.sort" type="number" :placeholder="$t('modelConfigDialog.enterSortOrder')"></el-input>
        </el-form-item>
      </div>

      <el-form-item :label="$t('modelConfigDialog.docLink')" prop="docUrl" style="margin-bottom: 27px">
        <el-input v-model="form.docLink" :placeholder="$t('modelConfigDialog.enterDocLink')"></el-input>
      </el-form-item>

      <el-form-item :label="$t('modelConfigDialog.remark')" prop="remark" class="prop-remark">
        <el-input v-model="form.remark" type="textarea" :rows="3" :autosize="{ minRows: 3, maxRows: 5 }" :placeholder="$t('modelConfigDialog.enterRemark')"></el-input>
      </el-form-item>
    </el-form>

    <teleport v-if="chunkedCallInfoFields.length">
      <div class="section-title">{{ $t("modelConfigDialog.callInfo") }}</div>
      <div class="section-divider"></div>
    </teleport>

    <el-form :model="form.configJson" ref="callInfoForm" label-width="auto" label-position="left">
      <template>
        <div v-for="(row, rowIndex) in chunkedCallInfoFields" :key="rowIndex" class="form-row">
          <el-form-item v-for="field in row" :key="field.prop" :label="field.label" :prop="field.prop"
            style="flex: 1">
            <template v-if="field.type === 'json-textarea'">
              <el-input v-model="fieldJsonMap[field.prop]" type="textarea" :rows="3"
                :placeholder="$t('modelConfigDialog.enterJsonExample')"
                @change="(val) => handleJsonChange(field.prop, val)" @focus="
                  isSensitiveField(field.prop)
                    ? handleJsonInputFocus(field.prop, fieldJsonMap[field.prop])
                    : undefined
                  " @blur="
                  isSensitiveField(field.prop)
                    ? handleJsonInputBlur(field.prop)
                    : undefined
                  "></el-input>
            </template>

            <el-select v-else-if="field.options.length" v-model="form.configJson[field.prop]"
              :placeholder="field.placeholder" style="width: 100%;">
              <el-option v-for="option in field.options" :key="option.value" :label="option.label"
                :value="option.value" />
            </el-select>

            <el-input v-else v-model="form.configJson[field.prop]" :placeholder="field.placeholder" :type="field.type"
              :show-password="field.type === 'password'" @focus="
                isSensitiveField(field.prop)
                  ? handleInputFocus(field.prop, form.configJson[field.prop])
                  : undefined
                " @blur="
                isSensitiveField(field.prop) ? handleInputBlur(field.prop) : undefined
                "></el-input>
          </el-form-item>
        </div>
      </template>
    </el-form>

    <div v-if="supportsUpstreamProbe" class="upstream-tools">
      <div>
        <div class="upstream-tools__title">{{ $t("modelConfigDialog.upstreamTools") }}</div>
        <div class="upstream-tools__hint">{{ $t("modelConfigDialog.upstreamToolsHint") }}</div>
      </div>
      <div class="upstream-tools__actions">
        <el-button :loading="modelsLoading" icon="el-icon-refresh" @click="fetchUpstreamModels(true)">
          {{ $t("modelConfigDialog.fetchUpstreamModels") }}
        </el-button>
        <el-button type="primary" :loading="testLoading" icon="el-icon-video-play" @click="openAndTest">
          {{ $t("modelConfigDialog.testConnection") }}
        </el-button>
      </div>
    </div>
    </div>

    <el-dialog
      :title="$t('modelConfigDialog.upstreamTestTitle')"
      :visible.sync="probeDialogVisible"
      width="620px"
      append-to-body
      :close-on-click-modal="false"
      custom-class="upstream-probe-dialog"
    >
      <div class="probe-model-row">
        <span class="probe-label">{{ $t("modelConfigDialog.testModel") }}</span>
        <el-select
          v-model="probeModel"
          filterable
          allow-create
          default-first-option
          style="flex: 1"
          :placeholder="$t('modelConfigDialog.selectOrEnterModel')"
          @change="applyProbeModel"
        >
          <el-option v-for="item in upstreamModels" :key="item.id" :label="item.name || item.id" :value="item.id" />
        </el-select>
        <el-button :loading="modelsLoading" icon="el-icon-refresh" @click="fetchUpstreamModels(false)">
          {{ $t("modelConfigDialog.refresh") }}
        </el-button>
      </div>

      <el-input
        v-model="probePrompt"
        class="probe-prompt"
        :placeholder="$t('modelConfigDialog.testPrompt')"
        maxlength="2000"
        show-word-limit
      />

      <div v-if="probeState" class="probe-result" :class="`probe-result--${probeState}`">
        <div class="probe-result__header">
          <span v-if="probeState === 'success'"><i class="el-icon-success"></i> {{ $t("modelConfigDialog.testSuccess") }}</span>
          <span v-else-if="probeState === 'error'"><i class="el-icon-error"></i> {{ $t("modelConfigDialog.testFailed") }}</span>
          <span v-else><i class="el-icon-info"></i> {{ $t("modelConfigDialog.modelsLoaded") }}</span>
          <span v-if="probeMeta" class="probe-result__meta">{{ probeMeta }}</span>
        </div>
        <pre>{{ probeMessage }}</pre>
      </div>

      <span slot="footer" class="dialog-footer probe-footer">
        <el-button @click="probeDialogVisible = false">{{ $t("modelConfigDialog.close") }}</el-button>
        <el-button type="primary" :loading="testLoading" icon="el-icon-refresh" @click="testUpstreamConnection">
          {{ $t("modelConfigDialog.runTest") }}
        </el-button>
      </span>
    </el-dialog>
  </CustomDialog>
</template>

<script>
import CustomDialog from './CustomDialog.vue';
import Api from "@/apis/api";

export default {
  name: "ModelEditDialog",
  components: { CustomDialog },
  props: {
    visible: { type: Boolean, default: false },
    modelData: {
      type: Object,
      default: () => ({}),
      validator: (value) => typeof value === "object" && !Array.isArray(value),
    },
    modelType: { type: String, required: true },
  },
  data() {
    return {
      dialogVisible: this.visible,
      providers: [],
      providersLoaded: false,
      saving: false,
      allProvidersData: null,
      pendingProviderType: null,
      pendingModelData: null,
      dynamicCallInfoFields: [],
      fieldJsonMap: {}, // 用于存储JSON字段的字符串形式
      sensitive_keys: [
        "api_key",
        "personal_access_token",
        "access_token",
        "token",
        "secret",
        "access_key_secret",
        "secret_key",
      ],
      originalValues: {}, // 存储原始值，用于失焦时恢复
      probeDialogVisible: false,
      upstreamModels: [],
      probeModel: "",
      probePrompt: "hi",
      probeState: "",
      probeMessage: "",
      probeMeta: "",
      modelsLoading: false,
      testLoading: false,
      form: {
        id: "",
        modelType: "",
        modelCode: "",
        modelName: "",
        isDefault: false,
        isEnabled: false,
        docLink: "",
        remark: "",
        sort: 0,
        configJson: {},
      },
    };
  },
  computed: {
    title() {
      return this.modelData.duplicateMode
        ? this.$t("modelConfigDialog.duplicateModel")
        : this.$t("modelConfigDialog.editModel");
    },
    chunkedCallInfoFields() {
      const chunkSize = 2;
      const result = [];
      for (let i = 0; i < this.dynamicCallInfoFields.length; i += chunkSize) {
        result.push(this.dynamicCallInfoFields.slice(i, i + chunkSize));
      }
      return result;
    },
    supportsUpstreamProbe() {
      const type = String(this.form.configJson.type || "").toLowerCase();
      return String(this.modelType || "").toLowerCase() === "llm"
        && ["anthropic_messages", "openai"].includes(type);
    },
  },
  watch: {
    modelType() {
      this.resetProviders();
      this.loadProviders();
    },
    visible(val) {
      this.dialogVisible = val;
    },
    dialogVisible(val) {
      this.$emit("update:visible", val);
    },
    "form.configJson.type"(newVal) {
      if (newVal && this.providersLoaded) {
        this.loadProviderFields(newVal);
      }
    },
  },
  methods: {
    handleOpen() {
      this.loadProviders();
      if (this.modelData.id) {
        this.loadModelData();
      }
    },
    handleClose() {
      this.saving = false;
      this.probeDialogVisible = false;
      // 处理关闭弹窗闪动问题
      setTimeout(() => {
        this.resetForm();
      }, 200)
    },
    resetForm() {
      this.form = {
        id: "",
        modelType: "",
        modelCode: "",
        modelName: "",
        isDefault: false,
        isEnabled: false,
        docLink: "",
        remark: "",
        sort: 0,
        configJson: {},
      };
      this.fieldJsonMap = {};
      this.upstreamModels = [];
      this.probeModel = "";
      this.probePrompt = "hi";
      this.probeState = "";
      this.probeMessage = "";
      this.probeMeta = "";
      this.modelsLoading = false;
      this.testLoading = false;
    },
    resetProviders() {
      this.providers = [];
      this.providersLoaded = false;
    },
    loadModelData() {
      if (this.modelData.id) {
        Api.model.getModelConfig(this.modelData.id, ({ data }) => {
          if (data.code === 0 && data.data) {
            let model = data.data;

            if (this.modelData.duplicateMode) {
              model.modelName =
                this.modelData.modelName + this.$t("modelConfigDialog.copySuffix");
              model.modelCode =
                this.modelData.modelCode + this.$t("modelConfigDialog.copySuffix");

              // 处理敏感字段
              if (model.configJson) {
                Object.keys(model.configJson).forEach((key) => {
                  if (this.isSensitiveField(key) && model.configJson[key]) {
                    const sensitiveName = this.getSensitiveFieldName(key);
                    model.configJson[key] = `你的${sensitiveName}`;
                  }
                });
              }
            }
            this.pendingProviderType = model.configJson.type;
            this.pendingModelData = model;

            if (this.providersLoaded) {
              this.loadProviderFields(model.configJson.type);
            } else {
              this.loadProviders();
            }
          }
        });
      }
    },
    handleSave() {
      this.saving = true; // 开始保存加载

      // 处理所有JSON字段
      Object.keys(this.fieldJsonMap).forEach((key) => {
        const parsed = this.validateJson(this.fieldJsonMap[key]);
        if (parsed !== null) {
          this.form.configJson[key] = parsed;
        }
      });

      const formData = {
        id: this.modelData.id,
        modelCode: this.form.modelCode,
        modelName: this.form.modelName,
        isDefault: this.form.isDefault ? 1 : 0,
        isEnabled: this.form.isEnabled ? 1 : 0,
        docLink: this.form.docLink,
        remark: this.form.remark,
        sort: this.form.sort || 0,
        configJson: { ...this.form.configJson },
      };

      this.$emit("save", {
        provideCode: this.form.configJson.type,
        formData,
        done: () => {
          this.saving = false; // 保存完成后回调
        },
      });

      // 如果父组件不处理done回调，3秒后自动关闭加载状态
      setTimeout(() => {
        this.saving = false;
      }, 3000);
    },
    syncJsonFields() {
      Object.keys(this.fieldJsonMap).forEach((key) => {
        const parsed = this.validateJson(this.fieldJsonMap[key]);
        if (parsed !== null) {
          this.form.configJson[key] = parsed;
        }
      });
    },
    probePayload() {
      this.syncJsonFields();
      return {
        modelId: this.modelData.duplicateMode ? null : (this.form.id || this.modelData.id || null),
        configJson: { ...this.form.configJson },
        modelName: this.probeModel || this.form.configJson.model_name || "",
        prompt: this.probePrompt || "hi",
      };
    },
    applyProbeModel(value) {
      this.probeModel = value;
      this.$set(this.form.configJson, "model_name", value);
    },
    fetchUpstreamModels(openDialog) {
      this.probeDialogVisible = openDialog || this.probeDialogVisible;
      this.modelsLoading = true;
      this.probeState = "";
      Api.model.getUpstreamModels(this.probePayload(), ({ data }) => {
        this.modelsLoading = false;
        const result = data.data || {};
        this.upstreamModels = Array.isArray(result.models) ? result.models : [];
        const current = this.form.configJson.model_name || this.probeModel;
        this.probeModel = current || (this.upstreamModels[0] && this.upstreamModels[0].id) || "";
        if (this.probeModel) this.applyProbeModel(this.probeModel);
        this.probeState = "models";
        this.probeMessage = this.$t("modelConfigDialog.modelsFound", { count: this.upstreamModels.length });
        this.probeMeta = `HTTP ${result.upstreamStatus || 200} · ${result.latencyMs || 0} ms`;
      }, (error) => {
        this.modelsLoading = false;
        this.showProbeError(error);
      });
    },
    openAndTest() {
      this.probeDialogVisible = true;
      this.probeModel = this.form.configJson.model_name || this.probeModel || "";
      this.$nextTick(() => this.testUpstreamConnection());
    },
    testUpstreamConnection() {
      this.probeDialogVisible = true;
      this.probeModel = this.probeModel || this.form.configJson.model_name || "";
      if (!this.probeModel) {
        this.probeState = "error";
        this.probeMessage = this.$t("modelConfigDialog.modelRequired");
        this.probeMeta = "";
        return;
      }
      this.applyProbeModel(this.probeModel);
      this.testLoading = true;
      this.probeState = "";
      Api.model.testUpstreamModel(this.probePayload(), ({ data }) => {
        this.testLoading = false;
        const result = data.data || {};
        this.probeState = "success";
        this.probeMessage = result.response || this.$t("modelConfigDialog.emptyResponse");
        this.probeMeta = `HTTP ${result.upstreamStatus || 200} · ${result.latencyMs || 0} ms`;
      }, (error) => {
        this.testLoading = false;
        this.showProbeError(error);
      });
    },
    showProbeError(error) {
      const responseData = error && error.data;
      this.probeState = "error";
      this.probeMessage = (responseData && responseData.msg)
        || (error && error.message)
        || this.$t("modelConfigDialog.unknownTestError");
      this.probeMeta = responseData && responseData.code ? `Code ${responseData.code}` : "";
    },
    loadProviders() {
      if (this.providersLoaded) return;

      Api.model.getModelProviders(this.modelType, (data) => {
        this.providers = data.map((item) => ({
          label: item.name,
          value: String(item.providerCode),
        }));
        this.providersLoaded = true;
        this.allProvidersData = data;

        if (this.pendingProviderType) {
          this.loadProviderFields(this.pendingProviderType);
        }
      });
    },
    loadProviderFields(providerCode) {
      if (this.allProvidersData) {
        const provider = this.allProvidersData.find(
          (p) => p.providerCode === providerCode
        );
        if (provider) {
          this.dynamicCallInfoFields = JSON.parse(provider.fields || "[]").map((f) => ({
            label: f.label,
            prop: f.key,
            type:
              f.type === "dict"
                ? "json-textarea"
                : f.type === "password"
                  ? "password"
                  : f.type === "number"
                    ? "number"
                    : "text",
            placeholder: f.placeholder || `请输入${f.key}`,
            defaultValue: Object.prototype.hasOwnProperty.call(f, "default") ? f.default : "",
            options: Array.isArray(f.options) ? f.options : [],
          }));

          if (this.pendingModelData && this.pendingProviderType === providerCode) {
            this.processModelData(this.pendingModelData);
            this.pendingModelData = null;
            this.pendingProviderType = null;
          }
        }
      }
    },
    processModelData(model) {
      let configJson = model.configJson || {};
      this.dynamicCallInfoFields.forEach((field) => {
        if (!configJson.hasOwnProperty(field.prop)) {
          configJson[field.prop] = field.defaultValue;
        } else if (field.type === "json-textarea") {
          this.$set(
            this.fieldJsonMap,
            field.prop,
            this.formatJson(configJson[field.prop])
          );
          configJson[field.prop] = this.ensureObject(configJson[field.prop]);
        } else if (typeof configJson[field.prop] !== "string") {
          configJson[field.prop] = String(configJson[field.prop]);
        }
      });

      this.form = {
        id: model.id,
        modelType: model.modelType,
        modelCode: model.modelCode,
        modelName: model.modelName,
        isDefault: model.isDefault,
        isEnabled: model.isEnabled,
        docLink: model.docLink,
        remark: model.remark,
        sort: Number(model.sort) || 0,
        configJson: { ...configJson },
      };
    },
    handleJsonChange(field, value) {
      const parsed = this.validateJson(value);
      if (parsed !== null) {
        this.form.configJson[field] = parsed;
      }
    },
    validateJson(value) {
      try {
        const parsed = JSON.parse(value);
        if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
          return parsed;
        }
        this.$message.error({
          message: '必须输入字典格式（如 {"key":"value"}），保存则使用原数据',
          showClose: true,
        });
        return null;
      } catch (e) {
        this.$message.error({
          message: 'JSON格式错误（如 {"key":"value"}），保存则使用原数据',
          showClose: true,
        });
        return null;
      }
    },
    formatJson(obj) {
      try {
        return JSON.stringify(obj, null, 2);
      } catch {
        return "";
      }
    },
    ensureObject(value) {
      return typeof value === "object" ? value : {};
    },

    // 检测字段是否为敏感字段
    isSensitiveField(fieldName) {
      // 将字段名转换为小写进行比较
      const lowerFieldName = fieldName.toLowerCase();
      // 精确匹配keyMap中定义的7个敏感词
      return this.sensitive_keys.includes(lowerFieldName);
    },

    // 获取敏感字段对应的中文名称
    getSensitiveFieldName(fieldName) {
      const keyMap = {
        api_key: "API密钥",
        personal_access_token: "个人访问令牌",
        access_token: "访问令牌",
        token: "令牌",
        secret: "密钥",
        access_key_secret: "访问密钥",
        secret_key: "密钥",
      };

      for (const [key, value] of Object.entries(keyMap)) {
        if (fieldName.toLowerCase().includes(key)) {
          return value;
        }
      }
      return "敏感信息";
    },

    // 处理input聚焦事件
    handleInputFocus(field, value) {
      // 如果值包含星号，清空显示
      if (value && value.includes("*")) {
        // 存储原始值，用于失焦时恢复
        this.$set(this.originalValues, field, this.form.configJson[field]);
        this.$set(this.form.configJson, field, "");
      }
    },

    // 处理input失焦事件
    handleInputBlur(field) {
      // 检查是否为敏感字段
      if (this.isSensitiveField(field)) {
        // 如果值为空，恢复掩码值
        if (!this.form.configJson[field] || this.form.configJson[field].trim() === "") {
          // 如果有原始值，则恢复原始值；否则设置为掩码提示
          if (this.originalValues[field]) {
            this.$set(this.form.configJson, field, this.originalValues[field]);
          } else {
            const sensitiveName = this.getSensitiveFieldName(field);
            this.$set(this.form.configJson, field, `你的${sensitiveName}`);
          }
          // 清除临时存储的原始值
          this.$delete(this.originalValues, field);
        }
      }
    },

    // 处理JSON字段的聚焦事件
    handleJsonInputFocus(field, value) {
      if (value && value.includes("*")) {
        this.$set(this.fieldJsonMap, field, "");
      }
    },

    // 处理JSON字段的失焦事件
    handleJsonInputBlur(field) {
      // JSON字段不做特殊处理，因为它们通常不包含简单的敏感信息
    },
  },
};
</script>

<style lang="scss" scoped>
@import '@/styles/global.scss';

::v-deep .el-dialog {
  margin-top: 6vh !important;
}
::v-deep .el-dialog__body {
  max-height: 60vh;
  overflow-y: auto;
  @include scrollbar-style;
}
.model-edit-dialog {
  .header-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .section-title {
    margin-bottom: 10px;
    font-size: 20px;
    font-weight: bold;
    color: #3d4566;
    text-align: left;
  }

  .switch-group {
    display: flex;
    align-items: center;
    gap: 20px;
  }

  .switch-item {
    display: flex;
    align-items: center;

    &.hidden {
      display: none;
    }

    .switch-label {
      margin-right: 8px;
    }
  }

  .section-divider {
    height: 1px;
    background: #e9e9e9;
    margin-bottom: 16px;
  }

  .form-row {
    display: flex;
    gap: 20px;
    margin-bottom: 0;
  }

  ::v-deep .el-input__inner {
    height: 32px;
  }
  ::v-deep .el-form-item {
    margin-bottom: 10px;
  }

  .upstream-tools {
    margin-top: 8px;
    padding: 14px 16px;
    border: 1px solid #dce6ff;
    border-radius: 8px;
    background: #f7f9ff;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }

  .upstream-tools__title {
    color: #303957;
    font-weight: 600;
    margin-bottom: 4px;
  }

  .upstream-tools__hint {
    color: #7b849f;
    font-size: 12px;
  }

  .upstream-tools__actions {
    display: flex;
    flex-shrink: 0;
  }
}

::v-deep .upstream-probe-dialog {
  border-radius: 12px;

  .probe-model-row {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .probe-label {
    color: #4b536e;
    font-weight: 600;
  }

  .probe-prompt {
    margin-top: 16px;
  }

  .probe-result {
    margin-top: 16px;
    padding: 14px 16px;
    border-radius: 8px;
    background: #101827;
    color: #d8e3f5;

    &--success .probe-result__header { color: #4ade80; }
    &--error .probe-result__header { color: #fb7185; }
    &--models .probe-result__header { color: #60a5fa; }

    pre {
      margin: 12px 0 0;
      padding-top: 12px;
      border-top: 1px solid rgba(255, 255, 255, 0.14);
      white-space: pre-wrap;
      word-break: break-word;
      font: 13px/1.65 Consolas, Monaco, monospace;
      max-height: 260px;
      overflow: auto;
    }
  }

  .probe-result__header {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    font-weight: 600;
  }

  .probe-result__meta {
    color: #94a3b8;
    font-size: 12px;
    font-weight: normal;
  }

  .probe-footer {
    display: flex;
    justify-content: flex-end;
  }
}
</style>
