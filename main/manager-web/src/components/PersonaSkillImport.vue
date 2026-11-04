<template>
  <div class="persona-skill-import">
    <div class="persona-skill-toolbar">
      <el-button
        type="primary"
        plain
        size="small"
        icon="el-icon-upload2"
        :aria-label="$t('personaSkill.importButton')"
        :disabled="disabled"
        :loading="reading"
        @click="chooseFile"
      >{{ $t('personaSkill.importButton') }}</el-button>
      <span class="persona-skill-count" :class="{ 'is-invalid': promptProblem }">
        {{ $t('personaSkill.size', { characters: size.characters, bytes: size.bytes, limit }) }}
      </span>
    </div>
    <input
      ref="fileInput"
      type="file"
      accept=".zip,.skill,.md,.txt,.json"
      hidden
      :disabled="disabled"
      :aria-label="$t('personaSkill.importButton')"
      @change="selectFile"
    />
    <p class="persona-skill-help">{{ $t('personaSkill.help') }}</p>
    <p v-if="promptProblem" class="persona-skill-error" role="alert">
      {{ $t(`personaSkill.errors.${promptProblem}`) }}
    </p>

    <el-dialog
      :title="$t('personaSkill.previewTitle')"
      :visible.sync="previewVisible"
      custom-class="persona-skill-dialog"
      top="6vh"
      :close-on-click-modal="false"
      append-to-body
      @closed="clearPreview"
    >
      <template v-if="preview">
        <el-alert
          :title="$t('personaSkill.replaceNotice', { agent: agentName })"
          type="info"
          :closable="false"
          show-icon
        />
        <div class="persona-skill-file-details">
          <span class="persona-skill-filename">{{ preview.filename }}</span>
          <span>{{ $t('personaSkill.size', { characters: preview.characters, bytes: preview.bytes, limit }) }}</span>
        </div>
        <p v-if="preview.strippedFrontmatter" class="persona-skill-help">
          {{ $t('personaSkill.metadataRemoved') }}
        </p>
        <div v-if="preview.archive" class="persona-skill-archive-details">
          <p class="persona-skill-help">{{ $t(`personaSkill.archiveModes.${preview.strategy}`) }}</p>
          <p class="persona-skill-source-label">{{ $t('personaSkill.sourceFiles') }}</p>
          <ul class="persona-skill-sources">
            <li v-for="name in preview.usedFiles" :key="name">{{ name }}</li>
          </ul>
          <p v-if="preview.verifiedFiles.length" class="persona-skill-help">
            {{ $t('personaSkill.verifiedFiles') }} {{ preview.verifiedFiles.join('、') }}
          </p>
          <p v-if="preview.alreadyIncludedFiles.length" class="persona-skill-help">
            {{ $t('personaSkill.alreadyIncluded') }} {{ preview.alreadyIncludedFiles.join('、') }}
          </p>
          <p v-if="preview.ignoredFiles" class="persona-skill-help">
            {{ $t('personaSkill.otherFiles', { count: preview.ignoredFiles }) }}
          </p>
        </div>
        <el-input
          type="textarea"
          :value="preview.prompt"
          :rows="preview.archive ? 8 : 12"
          readonly
          resize="vertical"
          :aria-label="$t('personaSkill.previewTitle')"
          class="persona-skill-preview-text"
        />
      </template>
      <span slot="footer">
        <el-button @click="cancelPreview">{{ $t('personaSkill.cancel') }}</el-button>
        <el-button type="primary" :disabled="disabled || !preview" @click="applyPreview">
          {{ $t('personaSkill.apply') }}
        </el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import { readPersonaSkill, promptSize, systemPromptProblem, SYSTEM_PROMPT_MAX_BYTES } from '@/utils/personaSkill';

export default {
  name: 'PersonaSkillImport',
  props: {
    value: { type: String, default: '' },
    agentName: { type: String, default: '' },
    disabled: { type: Boolean, default: false },
  },
  data() {
    return { reading: false, previewVisible: false, preview: null, readSequence: 0, limit: SYSTEM_PROMPT_MAX_BYTES };
  },
  computed: {
    size() { return promptSize(this.value); },
    promptProblem() { return systemPromptProblem(this.value); },
  },
  watch: {
    disabled(value) {
      if (value) this.cancelPreview();
    },
  },
  beforeDestroy() {
    this.readSequence += 1;
  },
  methods: {
    chooseFile() {
      if (!this.disabled && !this.reading) this.$refs.fileInput.click();
    },
    async selectFile(event) {
      const file = event.target.files?.[0];
      event.target.value = '';
      if (!file || this.disabled) return;
      const sequence = ++this.readSequence;
      this.reading = true;
      try {
        const preview = await readPersonaSkill(file);
        if (sequence !== this.readSequence || this.disabled) return;
        this.preview = preview;
        this.previewVisible = true;
      } catch (error) {
        if (sequence === this.readSequence) {
          this.$message.error(this.$t(`personaSkill.errors.${error.code || 'readFailed'}`));
        }
      } finally {
        if (sequence === this.readSequence) this.reading = false;
      }
    },
    applyPreview() {
      if (this.disabled || !this.preview) return;
      this.$emit('input', this.preview.prompt);
      this.cancelPreview();
      this.$message.success(this.$t('personaSkill.applied'));
    },
    cancelPreview() {
      this.readSequence += 1;
      this.reading = false;
      this.previewVisible = false;
      this.preview = null;
    },
    clearPreview() {
      // Do not clear a newer preview opened while an older dialog was closing.
      if (!this.previewVisible) this.preview = null;
    },
  },
};
</script>

<style scoped>
.persona-skill-import { margin-top: 10px; line-height: 1.5; }
.persona-skill-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; }
.persona-skill-count { color: #606266; font-size: 12px; }
.persona-skill-help { margin: 8px 0 0; color: #606266; font-size: 12px; text-indent: 0; text-align: left; }
.persona-skill-error, .persona-skill-count.is-invalid { color: #c23a36; }
.persona-skill-error { margin: 6px 0 0; font-size: 12px; }
.persona-skill-file-details { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin: 16px 0; font-size: 13px; color: #606266; }
.persona-skill-filename { color: #303133; font-weight: 600; overflow-wrap: anywhere; }
.persona-skill-preview-text { margin-top: 8px; }
.persona-skill-source-label { margin: 10px 0 4px; font-weight: 600; text-indent: 0; }
.persona-skill-sources { margin: 0 0 8px; padding-left: 20px; max-height: 100px; overflow-y: auto; overflow-wrap: anywhere; }
.persona-skill-archive-details p { overflow-wrap: anywhere; }
</style>

<style>
.persona-skill-dialog { width: 720px; max-width: calc(100vw - 32px); max-height: 88vh; display: flex; flex-direction: column; }
.persona-skill-dialog .el-dialog__body { padding-top: 12px; overflow-y: auto; min-height: 0; }
.persona-skill-dialog .el-dialog__header, .persona-skill-dialog .el-dialog__footer { flex-shrink: 0; }
.persona-skill-dialog .el-textarea__inner { line-height: 1.7; }
</style>
