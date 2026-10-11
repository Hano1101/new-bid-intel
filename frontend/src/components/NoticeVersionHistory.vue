<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import NoticeVersionDiff from './NoticeVersionDiff.vue'
import { createDatasetClient } from '../utils/datasets.js'
import { displayVersionValue, versionFieldLabels, versionIdentityLabel, versionLabel } from '../utils/versionDiff.js'

const props = defineProps({
  noticeId: { type: Number, required: true },
  datasetId: { type: String, required: true },
  apiBase: { type: String, default: '' },
  fetchImpl: { type: Function, default: (url, options) => fetch(url, { ...options, credentials: 'include' }) },
})
defineEmits(['open-evidence'])
const history = ref({ versions: [] })
const busy = ref(false)
const error = ref('')
const currentVersionId = ref('')
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')
const beforeVersionId = ref('')
const afterVersionId = ref('')
const comparison = ref(null)
const comparing = ref(false)
const comparisonError = ref('')
let requestVersion = 0
let historyGeneration = 0
let detailGeneration = 0
let comparisonGeneration = 0
const client = createDatasetClient(() => props.datasetId, () => requestVersion, (...args) => props.fetchImpl(...args))
const versions = computed(() => history.value.versions || [])
const selectedVersion = computed(() => versions.value.find(row => row.version_id === currentVersionId.value))
const snapshot = computed(() => detail.value?.snapshot || detail.value || {})
const metadata = computed(() => snapshot.value.metadata || snapshot.value.notice_metadata || {})
const files = computed(() => snapshot.value.source_files || selectedVersion.value?.source_files || [])
const beforeNoticeId = computed(() => versions.value.find(row => row.version_id === beforeVersionId.value)?.notice_id || null)
const afterNoticeId = computed(() => versions.value.find(row => row.version_id === afterVersionId.value)?.notice_id || null)
const canCompare = computed(() => Boolean(beforeVersionId.value && afterVersionId.value && beforeVersionId.value !== afterVersionId.value))
const identityPending = computed(() => ['identity_ambiguous', 'manual_link_required'].includes(history.value.identity_status))
const metadataKeys = ['project_name', 'project_number', 'procurement_unit', 'project_budget', 'announced_total_award']

async function request(path) {
  const response = await client(`${props.apiBase}/api/v1/notice-versions${path}`)
  const payload = await response.json()
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : '版本请求失败，请稍后重试。')
  return payload
}

async function selectVersion(versionId) {
  currentVersionId.value = versionId
  const generation = ++detailGeneration
  detail.value = null
  detailError.value = ''
  detailLoading.value = Boolean(versionId)
  if (!versionId) return
  try {
    const result = await request(`/versions/${encodeURIComponent(versionId)}`)
    if (generation === detailGeneration) detail.value = result
  } catch (cause) {
    if (generation === detailGeneration && cause.name !== 'AbortError') detailError.value = cause.message || '版本详情读取失败'
  } finally {
    if (generation === detailGeneration) detailLoading.value = false
  }
}

function clearComparison() {
  comparisonGeneration += 1
  comparison.value = null
  comparing.value = false
  comparisonError.value = ''
}

async function refresh() {
  const generation = ++historyGeneration
  detailGeneration += 1
  detail.value = null
  detailLoading.value = false
  detailError.value = ''
  clearComparison()
  busy.value = true
  error.value = ''
  try {
    const result = await request(`/notices/${encodeURIComponent(props.noticeId)}`)
    if (generation !== historyGeneration) return
    history.value = result
    const rows = result.versions || []
    const latest = result.latest_version_id || rows.find(row => row.is_latest)?.version_id || rows[0]?.version_id || ''
    const exists = id => rows.some(row => row.version_id === id)
    beforeVersionId.value = exists(beforeVersionId.value) ? beforeVersionId.value : rows.find(row => row.version_id !== latest)?.version_id || ''
    afterVersionId.value = exists(afterVersionId.value) ? afterVersionId.value : latest
    await selectVersion(exists(currentVersionId.value) ? currentVersionId.value : latest)
  } catch (cause) {
    if (generation === historyGeneration && cause.name !== 'AbortError') error.value = cause.message || '版本列表读取失败'
  } finally {
    if (generation === historyGeneration) busy.value = false
  }
}

async function compareVersions() {
  if (!canCompare.value) return
  const generation = ++comparisonGeneration
  comparison.value = null
  comparisonError.value = ''
  comparing.value = true
  const params = new URLSearchParams({ before_version_id: beforeVersionId.value, after_version_id: afterVersionId.value })
  try {
    const result = await request(`/compare?${params}`)
    if (generation === comparisonGeneration) comparison.value = result
  } catch (cause) {
    if (generation === comparisonGeneration && cause.name !== 'AbortError') comparisonError.value = cause.message || '版本比较失败'
  } finally {
    if (generation === comparisonGeneration) comparing.value = false
  }
}

watch([beforeVersionId, afterVersionId], clearComparison, { flush: 'sync' })
watch(() => [props.datasetId, props.noticeId, props.apiBase], () => {
  requestVersion += 1
  historyGeneration += 1
  detailGeneration += 1
  history.value = { versions: [] }
  currentVersionId.value = ''
  beforeVersionId.value = ''
  afterVersionId.value = ''
  detail.value = null
  detailLoading.value = false
  detailError.value = ''
  error.value = ''
  clearComparison()
  if (Number.isSafeInteger(props.noticeId) && props.noticeId > 0) refresh()
  else busy.value = false
}, { immediate: true, flush: 'sync' })

onBeforeUnmount(() => {
  requestVersion += 1
  historyGeneration += 1
  detailGeneration += 1
  comparisonGeneration += 1
})
</script>

<template>
  <section class="notice-versions" aria-label="公告和附件版本历史">
    <header class="notice-versions__header">
      <div><h3>公告和附件版本历史</h3><p>每个导入快照独立保留，可核对字段、文件指纹和来源变化。</p></div>
      <button type="button" class="secondary" :disabled="busy" @click="refresh">{{ busy ? '读取中…' : '刷新版本' }}</button>
    </header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="busy && !versions.length" class="notice-versions__empty" role="status">正在读取当前数据集的公告版本…</p>
    <p v-else-if="!versions.length && !error" class="notice-versions__empty">此公告尚无版本快照。历史数据不会自动补造版本；后续导入会保存新快照。</p>
    <template v-if="versions.length">
      <p class="notice-versions__identity" :class="{ 'is-pending': identityPending }">{{ versionIdentityLabel(history.identity_status) }}<template v-if="identityPending">：当前快照单独保留，人工确认关联后才能认定为同一公告。</template></p>
      <div class="notice-versions__list" aria-label="版本列表">
        <button v-for="version in versions" :key="version.version_id" type="button" class="notice-versions__row" :class="{ 'is-selected': currentVersionId === version.version_id }" :aria-pressed="currentVersionId === version.version_id" @click="selectVersion(version.version_id)">
          <strong>{{ versionLabel(version, history.latest_version_id) }}</strong>
          <span>{{ version.reason || '未保存版本来源说明' }}</span>
          <small>{{ versionIdentityLabel(version.identity_status) }} · {{ version.source_files?.length || 0 }} 个来源文件</small>
        </button>
      </div>
      <p v-if="detailLoading" class="notice-versions__empty" role="status">正在读取所选版本…</p>
      <p v-else-if="detailError" class="error" role="alert">{{ detailError }}</p>
      <section v-else-if="detail" class="notice-versions__detail" aria-label="所选版本详情">
        <h4>{{ versionLabel(selectedVersion, history.latest_version_id) }}</h4>
        <dl><div v-for="key in metadataKeys" :key="key"><dt>{{ versionFieldLabels[key] }}</dt><dd>{{ displayVersionValue(metadata[key]) }}</dd></div></dl>
        <h4>该版本的来源文件</h4>
        <article v-for="(file, index) in files" :key="`${file.source_file || file.filename}:${index}`" class="notice-versions__file">
          <strong>{{ file.source_file || file.filename || '来源文件名未保存' }}</strong>
          <code>SHA-256：{{ file.sha256 || '未保存' }}</code>
          <span>{{ file.byte_size ?? file.size_bytes ?? file.size ?? '未知' }} 字节 · {{ file.imported_at || selectedVersion?.imported_at || '导入时间未知' }}</span>
        </article>
        <p v-if="!files.length" class="notice-versions__empty">此版本没有保存来源文件清单。</p>
      </section>
      <section class="notice-versions__compare" aria-label="选择版本比较">
        <h4>比较两个版本</h4>
        <div class="notice-versions__selectors">
          <label>旧版本<select v-model="beforeVersionId" aria-label="旧版本"><option value="">请选择旧版本</option><option v-for="version in versions" :key="version.version_id" :value="version.version_id">{{ versionLabel(version, history.latest_version_id) }}</option></select></label>
          <label>新版本<select v-model="afterVersionId" aria-label="新版本"><option value="">请选择新版本</option><option v-for="version in versions" :key="version.version_id" :value="version.version_id">{{ versionLabel(version, history.latest_version_id) }}</option></select></label>
          <button type="button" class="secondary" :disabled="!canCompare || comparing || busy" @click="compareVersions">{{ comparing ? '比较中…' : '比较版本' }}</button>
        </div>
        <p v-if="versions.length < 2" class="notice-versions__hint">当前只有一个版本；同一公告的新快照导入后可以比较。</p>
        <p v-else-if="beforeVersionId && beforeVersionId === afterVersionId" class="notice-versions__hint">请选择两个不同版本。</p>
        <NoticeVersionDiff :comparison="comparison" :notice-id="noticeId" :before-notice-id="beforeNoticeId" :after-notice-id="afterNoticeId" :before-version-id="beforeVersionId" :after-version-id="afterVersionId" :loading="comparing" :error="comparisonError" @open-evidence="$emit('open-evidence', $event)" />
      </section>
    </template>
  </section>
</template>

<style scoped>
.notice-versions { display: grid; gap: 14px; padding-top: 18px; border-top: 1px solid #dce3ec; }
.notice-versions__header, .notice-versions__selectors { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
.notice-versions__header { justify-content: space-between; }
.notice-versions__header h3, .notice-versions__detail h4, .notice-versions__compare h4 { margin: 0 0 7px; }
.notice-versions__header p { margin: 0; color: #667085; font-size: .84rem; }
.notice-versions__identity { margin: 0; padding: 10px 12px; border-radius: 8px; background: #e8f2ec; color: #326a4e; }
.notice-versions__identity.is-pending { background: #fff2d8; color: #86500e; }
.notice-versions__list { display: grid; gap: 8px; max-height: 260px; overflow-y: auto; }
.notice-versions__row { display: grid; gap: 5px; padding: 12px; text-align: left; color: #29384b; background: #f7f9fb; border: 1px solid #dce3ec; border-radius: 8px; overflow-wrap: anywhere; }
.notice-versions__row.is-selected { border-color: #6085b7; background: #edf3fc; }
.notice-versions__row small, .notice-versions__row span { font-weight: normal; color: #667085; }
.notice-versions__detail { display: grid; gap: 10px; padding: 14px; background: #f8fafc; border-radius: 9px; }
.notice-versions__detail dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 0 0 5px; }
.notice-versions__detail dt { color: #667085; font-size: .76rem; }
.notice-versions__detail dd { margin: 4px 0 0; overflow-wrap: anywhere; }
.notice-versions__file { display: grid; gap: 5px; font-size: .84rem; padding: 10px; border: 1px solid #e0e7f0; border-radius: 7px; background: #fff; }
.notice-versions__file code { overflow-wrap: anywhere; }
.notice-versions__file span { color: #667085; }
.notice-versions__compare { display: grid; gap: 10px; }
.notice-versions__selectors { align-items: end; }
.notice-versions__selectors label { display: grid; gap: 5px; font-size: .83rem; flex: 1; min-width: 160px; }
.notice-versions__selectors select { width: 100%; min-width: 0; }
.notice-versions__empty { margin: 0; padding: 22px 12px; text-align: center; color: #667085; border: 1px dashed #ccd5e1; border-radius: 8px; }
.notice-versions__hint { margin: 0; font-size: .84rem; color: #667085; }
</style>
