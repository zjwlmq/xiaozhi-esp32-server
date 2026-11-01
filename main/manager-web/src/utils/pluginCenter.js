export function pluginStatus(packet, id, now = Date.now()) {
  const state = packet?.plugins?.[id]
  if (!state?.enabled) return { type: 'info', label: '未启用', detail: '开启后为当前智能体加载这项能力' }
  const manifest = packet.catalog?.plugins?.find(p => p.id === id)
  const missing = (manifest?.fields || []).filter(field => field.required &&
    (field.type === 'secret' ? !(state.configured_secrets || []).includes(field.key) : !String(state.settings?.[field.key] || '').trim()))
  if (missing.length) return { type: 'warning', label: '待配置', detail: '请设置' + missing.map(f => f.label).join('、') }
  const runtime = packet.runtime || {}
  if (!runtime.observed_at || now / 1000 - runtime.observed_at > 50) {
    return { type: 'warning', label: '待连接', detail: '设置已保存，等待设备连接并加载' }
  }
  if (runtime.revision !== packet.revision) {
    return { type: 'warning', label: '待生效', detail: '等待在线设备加载最新配置' }
  }
  const actual = runtime.plugins?.[id]
  const types = { ready: ['success', '已启用'], needs_config: ['warning', '待配置'], waiting: ['warning', '等待条件'], error: ['danger', '运行异常'], disabled: ['info', '未加载'] }
  const [type, label] = types[actual?.state] || ['warning', '待加载']
  return { type, label, detail: actual?.detail || '等待设备报告运行状态' }
}

export function settingsPatch(manifest, draft, clearedSecrets = {}) {
  const settings = {}
  for (const field of manifest.fields) {
    const value = draft[field.key]
    if (field.type === 'secret') {
      if (clearedSecrets[field.key]) settings[field.key] = null
      else if (value) settings[field.key] = value
    } else if (field.type === 'json') {
      let parsed
      try { parsed = Array.isArray(value) ? value : JSON.parse(value || '[]') } catch (_) { throw new Error(`${field.label}不是有效的 JSON`) }
      if (!Array.isArray(parsed)) throw new Error(`${field.label}需要填写数组`)
      const dates = new Set()
      parsed.forEach((day, index) => {
        const date = String(day?.date || '')
        const stamp = new Date(date)
        if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(stamp.getTime()) || stamp.toISOString().slice(0, 10) !== date) throw new Error(`请填写有效的日期（第 ${index + 1} 项）`)
        if (dates.has(date)) throw new Error('同一天只能有一条放假或调休安排')
        dates.add(date)
        if (typeof day.is_day_off !== 'boolean') throw new Error('请选择休息日或工作日')
      })
      settings[field.key] = parsed
    } else settings[field.key] = value
  }
  return { settings }
}
