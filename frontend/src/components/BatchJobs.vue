<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { createDatasetClient } from '../utils/datasets.js'

const props = defineProps({ apiBase: String, datasetId: String })
const emit = defineEmits(['updated'])
const mode = ref('hybrid')
const ocr = ref(true)
const selectedDirectory = ref(null)
const selectedPreflight = ref(null)
const browserOpen = ref(false)
const browser = ref(null)
const preflight = ref(null)
const browsing = ref(false)
const preflighting = ref(false)
const directoryError = ref('')
const jobs = ref([])
const error = ref('')
const busy = ref(false)
let version = 0
let timer
let disposed = false
let lastDone = -1
let browserRequest = 0
let preflightRequest = 0
let createRequest = 0
const client = createDatasetClient(() => props.datasetId, () => version)
const labels = { queued: '等待启动', running: '处理中', paused: '已暂停', interrupted: '已中断，可续跑', completed: '已完成', completed_with_errors: '完成，有失败公告' }

async function request(path, options) {
  const response = await client(props.apiBase + '/api/v1/jobs' + path, options)
  let result
  try { result = await response.json() } catch (cause) {
    if (cause.name === 'AbortError') throw cause
    if (!response.ok) throw new Error(`服务器请求失败（HTTP ${response.status}）`)
    throw new Error('服务器返回了无效响应')
  }
  if (!response.ok) throw new Error(result?.detail || `任务请求失败（HTTP ${response.status}）`)
  return result
}
async function refresh() {
  clearTimeout(timer)
  const current = version
  try {
    jobs.value = await request('')
    const done = jobs.value.reduce((sum, job) => sum + job.done, 0)
    if (done !== lastDone) { lastDone = done; emit('updated') }
  } catch (cause) {
    if (cause.name !== 'AbortError') error.value = cause.message
  } finally {
    if (!disposed && current === version) timer = setTimeout(refresh, 3000)
  }
}
async function create() {
  if (busy.value) return
  if (browserOpen.value || !selectedDirectory.value || !selectedPreflight.value?.can_start
      || selectedPreflight.value.directory_id !== selectedDirectory.value.directoryId
      || !selectedPreflight.value.preflight_fingerprint) {
    error.value = '请先浏览、预检并选择一个包含有效 HTML 公告的服务器目录'
    return
  }
  const current = ++createRequest
  busy.value = true
  error.value = ''
  try {
    await request('', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        directory_id: selectedDirectory.value.directoryId,
        preflight_fingerprint: selectedPreflight.value.preflight_fingerprint,
        mode: mode.value,
        ocr: ocr.value,
      }) })
    await refresh()
  } catch (cause) { if (cause.name !== 'AbortError') error.value = cause.message }
  finally { if (!disposed && current === createRequest) busy.value = false }
}
async function openBrowser(directoryId = selectedDirectory.value?.directoryId || '') {
  const current = ++browserRequest
  preflightRequest++
  browsing.value = true
  preflighting.value = false
  directoryError.value = ''
  selectedDirectory.value = null
  selectedPreflight.value = null
  preflight.value = null
  try {
    const result = await request('/directories?directory_id=' + encodeURIComponent(directoryId))
    if (disposed || current !== browserRequest) return
    browser.value = result
    browserOpen.value = true
    preflight.value = null
  } catch (cause) {
    if (!disposed && current === browserRequest && cause.name !== 'AbortError') directoryError.value = cause.message
  } finally { if (!disposed && current === browserRequest) browsing.value = false }
}
async function enterDirectory(directoryId) {
  preflight.value = null
  await openBrowser(directoryId)
}
async function checkDirectory() {
  if (!browserOpen.value || !browser.value || browsing.value) return
  const current = ++preflightRequest
  const currentBrowser = browserRequest
  const directoryId = browser.value.directory_id
  const isCurrent = () => !disposed && current === preflightRequest && currentBrowser === browserRequest
  preflighting.value = true
  directoryError.value = ''
  preflight.value = null
  try {
    const result = await request('/preflight?directory_id=' + encodeURIComponent(directoryId))
    if (!isCurrent()) return
    if (result.directory_id !== directoryId) throw new Error('预检目录与当前目录不一致，请重新预检')
    preflight.value = result
  } catch (cause) {
    if (isCurrent() && cause.name !== 'AbortError') directoryError.value = cause.message
  } finally { if (isCurrent()) preflighting.value = false }
}
function closeBrowser() {
  browserRequest++
  preflightRequest++
  browsing.value = false
  preflighting.value = false
  browserOpen.value = false
  preflight.value = null
}
function chooseDirectory() {
  if (!browserOpen.value || browsing.value || preflighting.value || !browser.value || !preflight.value?.can_start
      || preflight.value.directory_id !== browser.value.directory_id) return
  selectedDirectory.value = {
    directoryId: browser.value.directory_id,
    label: browser.value.directory_id || 'INTAKE_ROOT 根目录',
  }
  selectedPreflight.value = preflight.value
  closeBrowser()
  error.value = ''
}
function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unit = units[0]
  for (let index = 1; value >= 1024 && index < units.length; index += 1) {
    value /= 1024
    unit = units[index]
  }
  return `${value.toFixed(Number.isInteger(value) ? 0 : 1)} ${unit}`
}
async function action(job, operation) {
  try { await request('/' + job.id + '/' + operation, { method: 'POST' }); await refresh() }
  catch (cause) { if (cause.name !== 'AbortError') error.value = cause.message }
}
async function report(job) {
  try {
    const payload = await request('/' + job.id + '/report')
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url; link.download = 'batch-' + job.id + '.json'; link.click()
    URL.revokeObjectURL(url)
  } catch (cause) { if (cause.name !== 'AbortError') error.value = cause.message }
}
watch(() => props.datasetId, () => {
  version++
  browserRequest++
  preflightRequest++
  createRequest++
  jobs.value = []
  error.value = ''
  directoryError.value = ''
  selectedDirectory.value = null
  selectedPreflight.value = null
  browser.value = null
  preflight.value = null
  browserOpen.value = false
  browsing.value = false
  preflighting.value = false
  busy.value = false
  lastDone = -1
  refresh()
}, { immediate: true })
onBeforeUnmount(() => { disposed = true; version++; clearTimeout(timer) })
</script>

<template>
  <section class="panel batch-jobs">
    <div class="panel-heading"><h3>大批量后台处理</h3><span class="hint">关闭页面后继续运行，进度保存在本机</span></div>
    <p class="batch-note">选择后端已存放的材料目录；结果写入当前数据集。重跑整套数据前建议新建数据集。</p>
    <div class="job-form">
      <div class="directory-selection">
        <button type="button" class="secondary" :disabled="browsing" @click="openBrowser()">
          {{ browsing ? '正在读取目录…' : '浏览服务器材料目录' }}
        </button>
        <p v-if="selectedDirectory" class="batch-note selected-directory">已选择：{{ selectedDirectory.label }}</p>
        <p v-if="selectedPreflight" class="batch-note selected-summary">
          {{ selectedPreflight.html_count }} 条顶层公告 · {{ selectedPreflight.paired_archive_count }} 个配对附件 · {{ formatBytes(selectedPreflight.directory_bytes) }}
        </p>
      </div>
      <label>抽取方式<select v-model="mode"><option value="hybrid">模型主导混合（推荐）</option><option value="model">纯模型</option><option value="rules">规则基线</option></select></label>
      <label class="ocr-option"><input v-model="ocr" type="checkbox" />本地中文 OCR</label>
      <button class="primary" :disabled="busy || browserOpen || !selectedDirectory || !selectedPreflight?.can_start" @click="create">
        {{ busy ? '创建任务…' : '确认目录并开始后台处理' }}
      </button>
    </div>
    <p v-if="directoryError && !browserOpen" class="error" role="alert">{{ directoryError }}</p>
    <section v-if="browserOpen && browser" class="directory-browser" aria-label="服务器材料目录浏览器">
      <div class="browser-heading">
        <strong>当前目录：{{ browser.directory_id || browser.directory_name }}</strong>
        <button type="button" class="secondary" @click="closeBrowser">关闭</button>
      </div>
      <button v-if="browser.parent_directory_id !== null" type="button" class="secondary" :disabled="browsing" @click="enterDirectory(browser.parent_directory_id)">返回上级</button>
      <ul class="directory-list" v-if="browser.directories.length">
        <li v-for="entry in browser.directories" :key="entry.directory_id">
          <button type="button" class="directory-link" :disabled="browsing" @click="enterDirectory(entry.directory_id)">📁 {{ entry.name }}</button>
        </li>
      </ul>
      <p v-else class="batch-note">此目录没有可进入的子目录。</p>
      <button type="button" class="secondary" :disabled="preflighting || browsing" @click="checkDirectory">
        {{ preflighting ? '正在检查材料…' : '预检当前目录' }}
      </button>
      <p v-if="directoryError" class="error" role="alert">{{ directoryError }}</p>
      <section v-if="preflight" class="preflight-panel" aria-label="目录预检结果">
        <div class="preflight-grid">
          <p>顶层 HTML/HTM：<strong>{{ preflight.html_count }}</strong></p>
          <p>配对的同名 ZIP/RAR/7z：<strong>{{ preflight.paired_archive_count }}</strong></p>
          <p>未配对压缩材料：<strong>{{ preflight.unpaired_material_count }}</strong></p>
          <p>目录总字节数：<strong>{{ preflight.directory_bytes.toLocaleString() }} B</strong> <span>({{ formatBytes(preflight.directory_bytes) }})</span></p>
        </div>
        <p class="batch-note">{{ preflight.scan_note }}</p>
        <p v-if="preflight.skipped_symlink_count" class="batch-note">递归字节统计跳过 {{ preflight.skipped_symlink_count }} 个符号链接。</p>
        <p v-if="preflight.invalid_material_count" class="error" role="alert">
          发现 {{ preflight.invalid_material_count }} 个无效或符号链接公告/配对附件，修正后才能创建任务。
        </p>
        <p v-else-if="!preflight.html_count" class="error" role="alert">此目录没有可处理的顶层 HTML/HTM 公告。</p>
        <h4>公告与配对附件</h4>
        <ul class="preflight-list">
          <li v-for="notice in preflight.notices" :key="notice.html">
            <strong>{{ notice.html }}</strong>
            <span> — {{ notice.attachments.length ? notice.attachments.join('、') : '无同名附件' }}</span>
          </li>
        </ul>
        <p v-if="preflight.notices_truncated" class="batch-note">清单仅显示前 200 条公告。</p>
        <div v-if="preflight.unpaired_material_count">
          <h4>未配对压缩材料</h4>
          <ul class="preflight-list"><li v-for="name in preflight.unpaired_materials" :key="name">{{ name }}</li></ul>
          <p v-if="preflight.unpaired_materials_truncated" class="batch-note">仅显示前 200 个文件名。</p>
        </div>
        <button type="button" class="primary" :disabled="browsing || preflighting || !preflight.can_start || preflight.directory_id !== browser.directory_id" @click="chooseDirectory">选择此目录</button>
      </section>
    </section>
    <p v-if="mode !== 'rules'" class="batch-note">模型模式使用已配置的服务，会产生 API 调用费用。</p>
    <p v-if="error" class="error">{{ error }}</p>
    <article v-for="job in jobs" :key="job.id" class="job-row">
      <div class="job-title"><strong>{{ labels[job.status] || job.status }}</strong><span>{{ job.done }} / {{ job.notices_total }} 条 · {{ job.items }} 条候选 · {{ job.failed }} 条失败</span></div>
      <progress :value="job.done + job.failed" :max="job.notices_total" />
      <p class="batch-note">{{ job.source }} · {{ job.mode }} · {{ job.ocr ? 'OCR 开启' : 'OCR 关闭' }}</p>
      <p v-for="entry in job.active" :key="entry.index" class="active-file">{{ entry.name }} · {{ entry.documents_done }} / {{ entry.documents_total || '…' }} 份材料<br />{{ entry.current_file }}</p>
      <div class="job-actions">
        <button v-if="job.status === 'running'" class="secondary" @click="action(job, 'pause')">处理完当前文件后暂停</button>
        <button v-else-if="!['completed', 'completed_with_errors'].includes(job.status)" class="secondary" @click="action(job, 'resume')">继续处理</button>
        <button v-if="job.failed && job.status !== 'running'" class="secondary" @click="action(job, 'resume?retry_failed=true')">重试失败公告</button>
        <button class="secondary" @click="report(job)">下载处理报告</button>
      </div>
      <details v-if="job.errors.length"><summary>失败原因</summary><p v-for="entry in job.errors" :key="entry.name">{{ entry.name }}：{{ entry.error }}</p></details>
    </article>
  </section>
</template>

<style scoped>
.job-form { display:flex; flex-wrap:wrap; gap:16px; align-items:end; }
.job-form label { display:flex; flex-direction:column; gap:7px; flex:1; min-width:170px; }
.directory-selection { display:flex; flex-direction:column; gap:6px; flex:1 1 260px; min-width:220px; }
.selected-directory, .selected-summary { margin:0; overflow-wrap:anywhere; }
.job-form .ocr-option { flex-direction:row; align-items:center; flex:0 0 auto; min-width:auto; padding-bottom:12px; }
.ocr-option input { width:auto; }
.directory-browser, .preflight-panel { margin-top:18px; padding:18px; border:1px solid #dce4e8; border-radius:10px; background:#f8fbfa; }
.browser-heading { display:flex; gap:12px; align-items:center; justify-content:space-between; margin-bottom:12px; }
.directory-list, .preflight-list { margin:10px 0 18px; padding-left:22px; max-height:280px; overflow:auto; }
.directory-list li, .preflight-list li { margin:6px 0; overflow-wrap:anywhere; }
.directory-link { border:0; padding:3px 0; color:#176d66; background:transparent; text-align:left; cursor:pointer; }
.preflight-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:8px 16px; }
.preflight-grid p { margin:4px 0; }
.preflight-panel h4 { margin:18px 0 6px; }
.job-row { border-top:1px solid #dce4e8; margin-top:24px; padding-top:20px; }
.job-title, .job-actions { display:flex; flex-wrap:wrap; gap:12px; align-items:center; justify-content:space-between; }
.job-actions { justify-content:flex-start; }
progress { width:100%; height:12px; margin-top:14px; accent-color:#187d73; }
.active-file { font-size:12px; overflow-wrap:anywhere; color:#59716e; }
</style>
