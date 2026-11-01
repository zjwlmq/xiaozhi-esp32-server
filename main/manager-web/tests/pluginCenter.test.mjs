import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/utils/pluginCenter.js', import.meta.url), 'utf8')
const { pluginStatus, settingsPatch } = await import(`data:text/javascript,${encodeURIComponent(source)}`)
const mediaSource = readFileSync(new URL('../../digital-human/js/ui/plugin-image.js', import.meta.url), 'utf8')
const { safePluginImageUrl } = await import(`data:text/javascript,${encodeURIComponent(mediaSource)}`)
const now = 1000000
const packet = { revision: 3, plugins: { test: { enabled: true } }, runtime: { observed_at: 1000, revision: 3, plugins: { test: { state: 'ready', detail: '已加载' } } } }

test('saved config is not presented as running until the matching revision is reported', () => {
  assert.equal(pluginStatus(packet, 'test', now).type, 'success')
  assert.equal(pluginStatus({ ...packet, revision: 4 }, 'test', now).label, '待生效')
  assert.equal(pluginStatus({ ...packet, runtime: {} }, 'test', now).label, '待连接')
  assert.equal(pluginStatus(packet, 'test', now + 51000).label, '待连接')
})

test('disabled settings take priority over an old ready report', () => {
  const disabled = { ...packet, plugins: { test: { enabled: false } } }
  assert.equal(pluginStatus(disabled, 'test', now).label, '未启用')
})

test('missing required configuration is visible even before any device connects', () => {
  const incomplete = { plugins: { image: { enabled: true, settings: {}, configured_secrets: [] } },
    catalog: { plugins: [{ id: 'image', fields: [{ key: 'api_key', type: 'secret', label: 'API 密钥', required: true }] }] } }
  assert.equal(pluginStatus(incomplete, 'image', now).label, '待配置')
})

test('blank secret is omitted and explicit clear is sent as null', () => {
  const manifest = { fields: [{ key: 'api_key', type: 'secret' }, { key: 'model', type: 'text' }] }
  assert.deepEqual(settingsPatch(manifest, { api_key: '', model: 'test' }), { settings: { model: 'test' } })
  assert.deepEqual(settingsPatch(manifest, { api_key: '', model: 'test' }, { api_key: true }), { settings: { model: 'test', api_key: null } })
})

test('malformed calendar cannot be saved as an opaque string', () => {
  const manifest = { fields: [{ key: 'calendar', type: 'json', label: '日历' }] }
  assert.throws(() => settingsPatch(manifest, { calendar: 'not JSON' }), /JSON/)
  assert.throws(() => settingsPatch(manifest, { calendar: '{}' }), /数组/)
  assert.deepEqual(settingsPatch(manifest, { calendar: '[{"date":"2027-01-01","is_day_off":true}]' }).settings.calendar[0].is_day_off, true)
})

test('image rendering rejects active content and credentials in URLs', () => {
  for (const url of ['javascript:alert(1)', 'file:///etc/passwd', 'data:image/svg+xml;base64,PHN2Zz4=', 'https://user:pass@example.test/a.png']) {
    assert.equal(safePluginImageUrl(url), null)
  }
  assert.equal(safePluginImageUrl('https://example.test/a.png'), 'https://example.test/a.png')
  assert.equal(safePluginImageUrl('data:image/png;base64,aGVsbG8='), 'data:image/png;base64,aGVsbG8=')
})

test('calendar editor rejects impossible or repeated dates before sending settings', () => {
  const manifest = { fields: [{ key: 'calendar', type: 'json', label: '日历' }] }
  assert.throws(() => settingsPatch(manifest, { calendar: [{ date: '2027-02-30', is_day_off: true }] }), /有效的日期/)
  const day = { date: '2027-01-01', is_day_off: false, name: '个人排班' }
  assert.throws(() => settingsPatch(manifest, { calendar: [day, day] }), /同一天/)
  assert.deepEqual(settingsPatch(manifest, { calendar: [day] }), { settings: { calendar: [day] } })
})
