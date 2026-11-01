<template>
  <div class="plugin-page">
    <div class="plugin-navigation"><HeaderBar :devices="agents" /></div>
    <main class="plugin-main">
      <div class="page-heading">
        <div><div class="eyebrow">让每个人格拥有合适的能力</div><h1>插件中心</h1><p>选择智能体，按需开启。配置和运行状态都在这里。</p></div>
        <el-select v-model="agentId" placeholder="选择智能体" aria-label="选择智能体" @change="changeAgent" :disabled="initialLoading || saving">
          <el-option v-for="agent in agents" :key="agent.id" :value="agent.id" :label="agent.agentName" />
        </el-select>
      </div>
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="page-alert">
        <el-button type="text" @click="retry">重新加载</el-button>
      </el-alert>
      <div v-if="initialLoading || loading" class="loading-panel" aria-live="polite"><i class="el-icon-loading" /> 正在加载插件</div>
      <el-empty v-else-if="!agents.length" description="先创建一个智能体，再为它配置插件">
        <el-button type="primary" @click="$router.push('/home')">前往智能体管理</el-button>
      </el-empty>
      <template v-else-if="packet">
        <div class="overview">
          <div><strong>{{ enabledCount }}</strong><span>项已开启</span></div>
          <div><strong>{{ readyCount }}</strong><span>项已加载</span></div>
          <p><i class="el-icon-info" /> 状态来自最近在线的设备。主动消息仅在设备在线时发送。</p>
        </div>
        <div class="filter-row">
          <el-radio-group v-model="category" size="small" aria-label="插件分类">
            <el-radio-button v-for="item in categories" :key="item" :label="item" />
          </el-radio-group>
          <el-input v-model="search" class="plugin-search" placeholder="搜索插件" prefix-icon="el-icon-search" clearable aria-label="搜索插件" />
        </div>
        <div class="plugin-grid">
          <article v-for="plugin in visiblePlugins" :key="plugin.id" class="plugin-card" :class="{ enabled: state(plugin.id).enabled }">
            <div class="card-top"><span class="plugin-icon"><i :class="plugin.icon" /></span><el-tag :type="status(plugin.id).type" size="small" effect="plain">{{ status(plugin.id).label }}</el-tag></div>
            <h2>{{ plugin.name }}</h2><p class="plugin-description">{{ plugin.description }}</p>
            <p class="plugin-status" :class="{ failed: status(plugin.id).type === 'danger' }">{{ status(plugin.id).detail }}</p>
            <div v-if="plugin.dependencies.length" class="dependency">依赖：{{ dependencyNames(plugin) }}</div>
            <div v-else class="dependency">可独立使用</div>
            <div class="card-actions">
              <el-button size="small" plain @click="openSettings(plugin)" :disabled="!!busy[plugin.id]">配置</el-button>
              <div class="switch-wrap"><i v-if="busy[plugin.id]" class="el-icon-loading" /><span>{{ state(plugin.id).enabled ? '开启' : '关闭' }}</span>
                <el-switch :value="!!state(plugin.id).enabled" :disabled="!!busy[plugin.id]" :aria-label="`${plugin.name}开关`" @change="value => toggle(plugin, value)" />
              </div>
            </div>
          </article>
        </div>
        <el-empty v-if="!visiblePlugins.length" description="没有匹配的插件" />
      </template>
    </main>
    <el-drawer :visible.sync="drawer" :title="editing ? editing.name + '设置' : '插件设置'" size="min(520px, 100vw)" :wrapper-closable="!saving" :before-close="closeDrawer">
      <div v-if="editing" class="settings-body">
        <p class="settings-intro">{{ editing.description }}</p>
        <el-alert v-if="editing.dependencies.length" type="info" :closable="false" :title="'开启时会一并启用：' + dependencyNames(editing)" />
        <el-form label-position="top" class="settings-form" @submit.native.prevent="saveSettings">
          <el-form-item v-for="field in editing.fields" :key="field.key" :label="field.label">
            <el-switch v-if="field.type === 'boolean'" v-model="draft[field.key]" :aria-label="field.label" />
            <el-input-number v-else-if="field.type === 'integer'" v-model="draft[field.key]" :min="field.min" :max="field.max" :step="1" :precision="0" :aria-label="field.label" />
            <el-select v-else-if="field.type === 'select'" v-model="draft[field.key]" :aria-label="field.label"><el-option v-for="option in field.options" :key="option" :label="option" :value="option" /></el-select>
            <el-time-select v-else-if="field.type === 'time'" v-model="draft[field.key]" :picker-options="{start:'00:00',step:'00:15',end:'23:45'}" :clearable="false" :aria-label="field.label" />
            <div v-else-if="field.type === 'json'" class="calendar-editor">
              <p v-if="!draft[field.key].length" class="calendar-empty">还没有指定放假或调休日。节日识别仍会正常工作。</p>
              <div v-for="(day, index) in draft[field.key]" :key="index" class="calendar-day">
                <el-date-picker v-model="day.date" type="date" value-format="yyyy-MM-dd" placeholder="选择日期" :aria-label="'日期 ' + (index + 1)" />
                <el-select v-model="day.is_day_off" :aria-label="'安排 ' + (index + 1)"><el-option label="休息日" :value="true" /><el-option label="工作日" :value="false" /></el-select>
                <el-input v-model="day.name" placeholder="名称（可选）" :maxlength="80" :aria-label="'名称 ' + (index + 1)" />
                <el-button type="text" icon="el-icon-delete" :aria-label="'删除日期 ' + (index + 1)" @click="draft[field.key].splice(index, 1)">移除</el-button>
              </div>
              <el-button size="small" icon="el-icon-plus" aria-label="添加日期" :disabled="draft[field.key].length >= 800" @click="draft[field.key].push({date:'', name:'', is_day_off:true})">添加日期</el-button>
            </div>
            <template v-else-if="field.type === 'secret'">
              <el-input v-model="draft[field.key]" type="password" show-password autocomplete="new-password" :placeholder="secretConfigured(field.key) ? '已保存；输入新值可替换' : '填写 API 密钥'" :disabled="!!clearedSecrets[field.key]" :aria-label="field.label" />
              <el-checkbox v-if="secretConfigured(field.key)" v-model="clearedSecrets[field.key]">清除已保存的密钥</el-checkbox>
            </template>
            <el-input v-else v-model="draft[field.key]" :type="['textarea','json'].includes(field.type) ? 'textarea' : 'text'" :rows="field.type === 'json' ? 7 : 3" :maxlength="field.maxLength" :aria-label="field.label" />
            <div v-if="field.help" class="field-help">{{ field.help }}</div>
          </el-form-item>
          <el-alert v-if="saveError" :title="saveError" type="error" :closable="false" show-icon />
          <div class="drawer-actions"><el-button @click="drawer = false" :disabled="saving">取消</el-button><el-button type="primary" :loading="saving" @click="saveSettings">保存配置</el-button></div>
        </el-form>
      </div>
    </el-drawer>
  </div>
</template>

<script>
import HeaderBar from '@/components/HeaderBar.vue'
import api from '@/apis/module/pluginCenter'
import { pluginStatus, settingsPatch } from '@/utils/pluginCenter'

export default {
  name: 'PluginCenter', components: { HeaderBar },
  data: () => ({ agents: [], agentId: '', packet: null, initialLoading: true, loading: false, error: '', busy: {}, search: '', category: '全部', now: Date.now(), drawer: false, editing: null, draft: {}, clearedSecrets: {}, saving: false, saveError: '', generation: 0, timer: null }),
  computed: {
    plugins() { return this.packet?.catalog?.plugins || [] },
    categories() { return ['全部', ...new Set(this.plugins.map(p => p.category))] },
    visiblePlugins() { return this.plugins.filter(p => (this.category === '全部' || p.category === this.category) && `${p.name}${p.description}`.includes(this.search.trim())) },
    enabledCount() { return this.plugins.filter(p => this.state(p.id).enabled).length },
    readyCount() { return this.plugins.filter(p => this.status(p.id).type === 'success').length }
  },
  async mounted() {
    try {
      this.agents = await api.agents()
      const preferred = this.$route.query.agentId
      this.agentId = this.agents.some(a => a.id === preferred) ? preferred : (this.agents[0]?.id || '')
      await this.load()
    } catch (error) { this.error = error.message }
    finally { this.initialLoading = false }
    this.timer = setInterval(() => { this.now = Date.now(); if (!this.loading && !this.saving && !Object.values(this.busy).some(Boolean)) this.load(true) }, 10000)
  },
  beforeDestroy() { clearInterval(this.timer); this.generation++ },
  methods: {
    state(id) { return this.packet?.plugins?.[id] || {} },
    status(id) { return pluginStatus(this.packet, id, this.now) },
    dependencyNames(plugin) { return plugin.dependencies.map(id => this.plugins.find(p => p.id === id)?.name || id).join('、') },
    async load(quiet = false) {
      if (!this.agentId) return
      const generation = ++this.generation
      if (!quiet) this.loading = true
      try { const packet = await api.get(this.agentId); if (generation === this.generation) { this.packet = packet; this.error = '' } }
      catch (error) { if (generation === this.generation) this.error = error.message }
      finally { if (generation === this.generation) this.loading = false }
    },
    async retry() {
      if (this.agentId) { await this.load(); return }
      this.initialLoading = true
      try { this.agents = await api.agents(); this.agentId = this.agents[0]?.id || ''; this.error = ''; await this.load() }
      catch (error) { this.error = error.message }
      finally { this.initialLoading = false }
    },
    acceptMutation(packet, agentId) {
      if (agentId === this.agentId && (!this.packet || packet.revision >= this.packet.revision)) this.packet = packet
    },
    async changeAgent() { this.drawer = false; this.packet = null; this.category = '全部'; this.busy = {}; await this.load() },
    async toggle(plugin, enabled) {
      const agentId = this.agentId
      this.generation++
      this.$set(this.busy, plugin.id, true)
      try {
        const packet = await api.update(agentId, plugin.id, { enabled })
        if (agentId === this.agentId) { this.acceptMutation(packet, agentId); this.$message.success(enabled ? '已保存，在线设备将自动加载' : '已保存关闭设置') }
      } catch (error) { this.$message.error(error.message) }
      finally { if (agentId === this.agentId) this.$set(this.busy, plugin.id, false) }
    },
    openSettings(plugin) {
      this.editing = plugin; this.draft = {}; this.clearedSecrets = {}; this.saveError = ''
      for (const field of plugin.fields) {
        let value = this.state(plugin.id).settings?.[field.key] ?? field.default
        if (field.type === 'json') value = JSON.parse(JSON.stringify(value))
        if (field.type === 'secret') value = ''
        this.$set(this.draft, field.key, value)
        this.$set(this.clearedSecrets, field.key, false)
      }
      this.drawer = true
    },
    secretConfigured(key) { return (this.state(this.editing.id).configured_secrets || []).includes(key) },
    closeDrawer(done) { if (!this.saving) done() },
    async saveSettings() {
      const agentId = this.agentId
      let patch
      try { patch = settingsPatch(this.editing, this.draft, this.clearedSecrets) } catch (error) { this.saveError = error.message; return }
      this.saving = true; this.saveError = ''; this.generation++
      try {
        const packet = await api.update(agentId, this.editing.id, patch)
        if (agentId === this.agentId) { this.acceptMutation(packet, agentId); this.drawer = false; this.$message.success('配置已保存') }
      } catch (error) { this.saveError = error.message }
      finally { this.saving = false }
    }
  }
}
</script>

<style scoped>
.plugin-navigation{max-width:100%;overflow-x:auto}
.calendar-day{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px;margin-bottom:14px;padding:12px;border:1px solid #e4eaf4;border-radius:8px}.calendar-day .el-date-editor{width:100%}.calendar-empty{font-size:12px;color:#72819a;line-height:1.7}
.plugin-page{min-height:100vh;background:#f5f7fb;color:#25324b}.plugin-main{max-width:1180px;margin:auto;padding:36px 28px 64px}.page-heading{display:flex;justify-content:space-between;align-items:center;gap:24px;margin-bottom:28px}.eyebrow{font-size:13px;color:#72819a;letter-spacing:.04em}h1{font-size:30px;margin:9px 0 10px;font-weight:650}.page-heading p,.settings-intro{color:#72819a;font-size:14px;line-height:1.7;margin:0}.overview{display:flex;align-items:center;gap:32px;padding:22px 24px;border:1px solid #e4eaf4;border-radius:14px;background:white;margin:24px 0}.overview strong{font-size:28px;margin-right:9px;color:#4a6de5}.overview span,.overview p{font-size:13px;color:#72819a}.overview p{margin-left:auto;max-width:420px;line-height:1.6}.filter-row{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:28px 0 20px}.plugin-search{max-width:240px}.plugin-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.plugin-card{display:flex;flex-direction:column;background:white;padding:24px;border-radius:14px;border:1px solid #e4eaf4;transition:border-color .18s ease}.plugin-card.enabled{border-color:#c3d0ff}.card-top{display:flex;justify-content:space-between;align-items:center}.plugin-icon{display:flex;align-items:center;justify-content:center;width:46px;height:46px;border-radius:12px;background:#edf2ff;color:#5372d9;font-size:25px}.plugin-card h2{font-size:18px;margin:20px 0 10px}.plugin-description{font-size:14px;color:#68758d;line-height:1.8;min-height:50px;margin:0 0 16px}.plugin-status{font-size:12px;line-height:1.6;color:#8390a6;margin:0 0 8px;min-height:38px}.plugin-status.failed{color:#cb5353}.dependency{font-size:12px;color:#8793a7;margin-top:auto;padding-bottom:18px}.card-actions{display:flex;justify-content:space-between;align-items:center;border-top:1px solid #eff2f7;padding-top:18px}.switch-wrap{display:flex;align-items:center;gap:8px;font-size:12px;color:#7c899e}.settings-body{padding:0 26px 30px}.settings-intro{margin-bottom:18px}.settings-form{margin-top:22px}.field-help{font-size:12px;line-height:1.7;color:#8290a6;margin-top:8px;white-space:pre-wrap;word-break:break-word}.drawer-actions{position:sticky;bottom:0;padding:20px 0;background:white;text-align:right;border-top:1px solid #edf0f6}.loading-panel{text-align:center;padding:80px;color:#75849a}.page-alert{margin-bottom:20px}.settings-body .el-select{width:100%}@media(max-width:960px){.plugin-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.overview{gap:18px}.overview p{max-width:280px}}@media(max-width:640px){.plugin-main{padding:24px 16px}.page-heading{align-items:flex-start;flex-direction:column}.overview{flex-wrap:wrap}.overview p{margin:0;max-width:none}.filter-row{align-items:flex-start;flex-direction:column}.plugin-grid{grid-template-columns:1fr}.plugin-search{max-width:none}}@media(prefers-reduced-motion:reduce){.plugin-card{transition:none}}
</style>
