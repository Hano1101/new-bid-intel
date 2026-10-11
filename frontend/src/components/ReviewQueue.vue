<script setup>
import { computed, ref, watch } from 'vue'
import { createDatasetClient } from '../utils/datasets.js'
import { hasReviewSourceEvidence, reviewCandidateKey, reviewCorrectionValues, reviewEvidenceTarget, reviewPackageLabel, reviewSourceEvidence, reviewWarningDetails } from '../utils/reviewQueue.js'

const props = defineProps({
  apiBase: { type: String, required: true },
  datasetId: { type: String, required: true },
  fetchImpl: { type: Function, default: fetch },
})
const emit = defineEmits(['open-notice'])
const statusFilter = ref('pending')
const typeFilter = ref('')
const queue = ref({ items: [], total: 0, limit: 20, offset: 0 })
const busy = ref(false)
const error = ref('')
const message = ref('')
const draft = ref(null)
const historyOpen = ref('')
const historyByKey = ref({})
const historyErrors = ref({})
const pageSize = 20
let requestVersion = 0
let refreshGeneration = 0
let historyGeneration = 0
const client = createDatasetClient(() => props.datasetId, () => requestVersion, (...args) => props.fetchImpl(...args))

const pageNumber = computed(() => Math.floor(queue.value.offset / pageSize) + 1)
const pageCount = computed(() => Math.max(1, Math.ceil(queue.value.total / pageSize)))
const types = [
  { value: 'item', label: '标的物' },
  { value: 'bid', label: '投标记录' },
  { value: 'award', label: '中标记录' },
]
const fieldLabels = {
  package_code: '包号', product_name: '标的名称', category: '品目', brand: '品牌', model: '规格型号',
  quantity: '数量', quantity_unit: '数量单位', unit_price: '单价', total_price: '总价',
  organization_name: '主体名称', outcome: '投标结果', award_amount: '中标金额',
}
const fieldSets = {
  item: ['package_code', 'product_name', 'category', 'brand', 'model', 'quantity', 'quantity_unit', 'unit_price', 'total_price'],
  bid: ['package_code', 'organization_name', 'outcome'],
  award: ['package_code', 'organization_name', 'award_amount'],
}

function rowKey(row) {
  return reviewCandidateKey(row)
}

function labelForType(type) {
  return types.find(item => item.value === type)?.label || type
}

function show(value) {
  return value === null || value === undefined || (typeof value === 'string' && !value.trim()) ? '—' : String(value)
}

function displayName(row) {
  return row.product_name || row.organization_name || `候选 #${row.candidate_id}`
}

function fieldEditors(row) {
  return fieldSets[row.candidate_type].map(key => ({
    key,
    label: fieldLabels[key],
    numeric: ['quantity', 'unit_price', 'total_price', 'award_amount'].includes(key),
    options: key === 'outcome' ? [
      { value: 'winner', label: '中标' },
      { value: 'nonwinner', label: '未中标' },
      { value: 'unknown', label: '未知' },
    ] : null,
  }))
}

async function request(path, options = {}) {
  const response = await client(`${props.apiBase}/api/v1/review-queue${path}`, options)
  const payload = await response.json()
  if (!response.ok) throw new Error(payload.detail || '复核队列请求失败')
  return payload
}

async function refresh() {
  const generation = ++refreshGeneration
  historyGeneration += 1
  historyByKey.value = {}
  historyErrors.value = {}
  busy.value = true
  error.value = ''
  const params = new URLSearchParams({ status: statusFilter.value, limit: String(pageSize), offset: String(queue.value.offset || 0) })
  if (typeFilter.value) params.set('candidate_type', typeFilter.value)
  try {
    let result
    while (true) {
      result = await request(`?${params}`)
      if (generation !== refreshGeneration) return
      if (result.offset === 0 || result.offset < result.total) break
      const lastOffset = Math.max(0, Math.floor((result.total - 1) / pageSize) * pageSize)
      params.set('offset', String(lastOffset))
    }
    queue.value = result
    const openRow = result.items.find(row => rowKey(row) === historyOpen.value)
    if (openRow) await loadHistory(openRow)
    else historyOpen.value = ''
  } catch (cause) {
    if (generation === refreshGeneration && cause.name !== 'AbortError') error.value = cause.message || '复核队列读取失败'
  } finally {
    if (generation === refreshGeneration) busy.value = false
  }
}

function changeFilter() {
  queue.value.offset = 0
  draft.value = null
  message.value = ''
  return refresh()
}

function changePage(offset) {
  queue.value.offset = offset
  return refresh()
}

function startDecision(row, action) {
  draft.value = {
    key: rowKey(row),
    candidateEpoch: row.candidate_epoch,
    action,
    reason: '',
    originalValues: { ...row.values },
    values: Object.fromEntries(fieldSets[row.candidate_type].map(key => [key, row.values[key] ?? ''])),
  }
  message.value = ''
  error.value = ''
}

function cancelDecision() {
  draft.value = null
}

async function submitDecision(row) {
  if (!draft.value || draft.value.key !== rowKey(row)) return
  const version = requestVersion
  const payload = {
    action: draft.value.action,
    reason: draft.value.reason,
    candidate_epoch: draft.value.candidateEpoch,
  }
  if (payload.action === 'corrected') {
    payload.corrected_values = reviewCorrectionValues(draft.value.values, draft.value.originalValues)
    if (!Object.keys(payload.corrected_values).length) {
      error.value = '请至少修改一个字段后再保存修正。'
      return
    }
  }
  busy.value = true
  error.value = ''
  try {
    const result = await request(`/${row.candidate_type}/${row.candidate_id}/decisions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (version !== requestVersion) return
    message.value = `已记录${{ accepted: '接受', corrected: '修正', rejected: '驳回' }[result.action]}决定（${result.actor} · ${result.created_at}）`
    draft.value = null
    await refresh()
  } catch (cause) {
    if (version === requestVersion && cause.name !== 'AbortError') error.value = cause.message || '提交复核决定失败'
  } finally {
    if (version === requestVersion) busy.value = false
  }
}

async function loadHistory(row) {
  const key = rowKey(row)
  const generation = ++historyGeneration
  delete historyErrors.value[key]
  try {
    const result = await request(`/${row.candidate_type}/${row.candidate_id}/history`)
    if (generation === historyGeneration && historyOpen.value === key) {
      historyByKey.value = { ...historyByKey.value, [key]: result }
    }
  } catch (cause) {
    if (generation === historyGeneration && historyOpen.value === key && cause.name !== 'AbortError') {
      historyErrors.value = { ...historyErrors.value, [key]: cause.message || '读取复核历史失败' }
    }
  }
}

async function toggleHistory(row) {
  const key = rowKey(row)
  if (historyOpen.value === key) {
    historyGeneration += 1
    historyOpen.value = ''
    return
  }
  historyOpen.value = key
  if (historyByKey.value[key]) return
  await loadHistory(row)
}

function openEvidence(row) {
  emit('open-notice', reviewEvidenceTarget(row))
}

watch(() => props.datasetId, () => {
  requestVersion += 1
  refreshGeneration += 1
  queue.value = { items: [], total: 0, limit: pageSize, offset: 0 }
  draft.value = null
  historyOpen.value = ''
  historyByKey.value = {}
  historyErrors.value = {}
  message.value = ''
  refresh()
}, { immediate: true })
</script>

<template>
  <section class="panel review-queue view-panel" aria-labelledby="review-queue-title">
    <header class="review-queue__header">
      <div>
        <p class="eyebrow">MANUAL REVIEW</p>
        <h2 id="review-queue-title">人工复核队列</h2>
        <p>队列依据可观察的数据缺失、来源和解析告警排序。复核决定独立保存，不会改写抽取候选或分析结果。</p>
      </div>
      <span class="review-queue__badge">人工判断</span>
    </header>

    <p class="review-queue__boundary">这些提示仅帮助查找需要核验的记录，不构成对任何主体或项目的违法、围标或串标判断。</p>

    <div class="review-queue__filters">
      <label>处理状态
        <select v-model="statusFilter" @change="changeFilter">
          <option value="pending">待复核</option>
          <option value="processed">已处理</option>
          <option value="all">全部状态</option>
        </select>
      </label>
      <label>候选类型
        <select v-model="typeFilter" @change="changeFilter">
          <option value="">全部类型</option>
          <option v-for="type in types" :key="type.value" :value="type.value">{{ type.label }}</option>
        </select>
      </label>
      <button class="secondary" type="button" :disabled="busy" @click="refresh">{{ busy ? '读取中…' : '刷新队列' }}</button>
      <span class="review-queue__count">{{ queue.total }} 条</span>
    </div>

    <p v-if="message" class="notice" role="status">{{ message }}</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <div v-if="busy && !queue.items.length" class="review-queue__empty">正在读取当前数据集的复核项…</div>
    <div v-else-if="!queue.items.length" class="review-queue__empty">
      {{ statusFilter === 'pending' ? '当前筛选下没有待复核项。导入公告后，符合数据质量规则的候选会显示在这里。' : '当前筛选下没有复核记录。' }}
    </div>

    <article v-for="row in queue.items" :key="rowKey(row)" class="review-card">
      <header class="review-card__head">
        <div>
          <div class="review-card__labels">
            <span class="review-card__priority">P{{ row.priority.rank }} · {{ row.priority.label }}</span>
            <span class="review-card__type">{{ labelForType(row.candidate_type) }}</span>
            <span class="review-card__status" :class="`is-${row.status}`">{{ row.status === 'pending' ? '待复核' : '已处理' }}</span>
          </div>
          <h3>{{ displayName(row) }}</h3>
          <p>{{ row.project_name || row.project_number || '未保存项目名称' }} · {{ row.package_name || `包号 ${show(row.package_code)}` }}</p>
        </div>
        <button class="secondary" type="button" @click="openEvidence(row)">查看公告与来源</button>
      </header>

      <div class="review-card__context">
        <span>公告 #{{ row.notice_id }}</span>
        <span>项目编号：{{ show(row.project_number) }}</span>
        <span>包号：{{ show(row.package_code) }}<template v-if="row.package_code === 'default'">（系统默认值）</template></span>
      </div>

      <section class="review-card__signals" aria-label="进入队列的原因">
        <h4>进入队列的原因</h4>
        <ul><li v-for="(reason, index) in row.reasons" :key="`${reason.code}-${index}`">{{ reason.detail }}</li></ul>
      </section>

      <section v-if="reviewWarningDetails(row).length" class="review-card__warnings" aria-label="解析和附件告警">
        <h4>关联解析 / OCR / 附件告警</h4>
        <p v-for="warning in reviewWarningDetails(row)" :key="warning">{{ warning }}</p>
      </section>

      <section class="review-card__values">
        <h4>系统原始候选值</h4>
        <dl>
          <div v-for="(value, key) in row.values" :key="key"><dt>{{ fieldLabels[key] || key }}</dt><dd>{{ key === 'package_code' ? reviewPackageLabel(value) : show(value) }}</dd></div>
        </dl>
        <div class="review-card__source">
          <strong>来源位置</strong><span>{{ show(row.source_file) }} · {{ show(row.source_location) }}</span>
          <strong>来源片段</strong><span :class="{ 'is-missing': !hasReviewSourceEvidence(row) }">{{ reviewSourceEvidence(row) }}</span>
        </div>
      </section>

      <section v-if="row.latest_review" class="review-card__decision">
        <strong>最近决定：{{ { accepted: '接受', corrected: '修正', rejected: '驳回' }[row.latest_review.action] }}</strong>
        <span>{{ row.latest_review.actor }} · {{ row.latest_review.created_at }}</span>
        <p>理由：{{ row.latest_review.reason }}</p>
        <div v-if="Object.keys(row.latest_review.changes).length" class="review-card__changes">
          <div v-for="(change, key) in row.latest_review.changes" :key="key">
            <strong>{{ fieldLabels[key] || key }}</strong><span>{{ show(change.before) }} → {{ show(change.after) }}</span>
          </div>
        </div>
      </section>

      <div class="review-card__actions">
        <template v-if="row.status === 'pending'">
          <button class="secondary" type="button" :disabled="busy" @click="startDecision(row, 'accepted')">接受</button>
          <button class="secondary" type="button" :disabled="busy" @click="startDecision(row, 'corrected')">修正</button>
          <button class="secondary" type="button" :disabled="busy" @click="startDecision(row, 'rejected')">驳回</button>
        </template>
        <button class="source-open" type="button" @click="toggleHistory(row)">{{ historyOpen === rowKey(row) ? '收起复核历史' : '查看复核历史' }}</button>
      </div>

      <section v-if="draft?.key === rowKey(row)" class="review-card__form">
        <h4>{{ { accepted: '接受候选', corrected: '修正候选', rejected: '驳回候选' }[draft.action] }}</h4>
        <template v-if="draft.action === 'corrected'">
          <div class="review-card__edit-grid">
            <label v-for="field in fieldEditors(row)" :key="field.key">{{ field.label }}
              <select v-if="field.options" v-model="draft.values[field.key]">
                <option v-for="option in field.options" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
              <input v-else v-model="draft.values[field.key]" :type="field.numeric ? 'number' : 'text'" :step="field.numeric ? 'any' : undefined" />
            </label>
          </div>
          <p class="review-queue__boundary">修改值只保存在复核记录中；系统原始候选、包关系、分析和评测数据保持不变。</p>
        </template>
        <label>复核理由<textarea v-model="draft.reason" rows="3" maxlength="2000" required placeholder="记录接受、修正或驳回的依据"></textarea></label>
        <div class="review-card__actions">
          <button class="primary" type="button" :disabled="busy || !draft.reason.trim()" @click="submitDecision(row)">保存决定</button>
          <button class="secondary" type="button" :disabled="busy" @click="cancelDecision">取消</button>
        </div>
      </section>

      <section v-if="historyOpen === rowKey(row)" class="review-card__history">
        <h4>复核历史</h4>
        <p v-if="historyErrors[rowKey(row)]" class="error" role="alert">{{ historyErrors[rowKey(row)] }}</p>
        <p v-else-if="!historyByKey[rowKey(row)]">正在读取历史…</p>
        <p v-else-if="!historyByKey[rowKey(row)].events.length">尚无复核事件。</p>
        <article v-for="event in historyByKey[rowKey(row)]?.events || []" :key="event.id">
          <strong>{{ { accepted: '接受', corrected: '修正', rejected: '驳回' }[event.action] }} · {{ event.actor }} · {{ event.created_at }}</strong>
          <p v-if="event.candidate_epoch !== row.candidate_epoch">历史候选版本 {{ event.candidate_epoch }}（当前版本 {{ row.candidate_epoch }}）</p>
          <p>{{ event.reason }}</p>
          <div v-for="(change, key) in event.changes" :key="key">{{ fieldLabels[key] || key }}：{{ show(change.before) }} → {{ show(change.after) }}</div>
        </article>
      </section>
    </article>

    <footer v-if="queue.total > pageSize" class="review-queue__pagination">
      <button class="secondary" type="button" :disabled="busy || queue.offset === 0" @click="changePage(Math.max(0, queue.offset - pageSize))">上一页</button>
      <span>第 {{ pageNumber }} / {{ pageCount }} 页</span>
      <button class="secondary" type="button" :disabled="busy || queue.offset + pageSize >= queue.total" @click="changePage(queue.offset + pageSize)">下一页</button>
    </footer>
  </section>
</template>

<style scoped>
.review-queue { display: grid; gap: 18px; }
.review-queue__header, .review-card__head, .review-queue__filters, .review-queue__pagination,
.review-card__actions, .review-card__labels { display: flex; align-items: center; gap: 12px; }
.review-queue__header, .review-card__head { justify-content: space-between; }
.review-queue__header h2 { margin: 4px 0 6px; }
.review-queue__header p, .review-card__head p { margin: 0; color: var(--muted, #6b7280); }
.review-queue__badge, .review-card__priority, .review-card__type, .review-card__status { border-radius: 999px; padding: 5px 10px; background: #edf2f7; font-size: .78rem; }
.review-queue__badge { color: #175c4a; background: #e5f4ee; white-space: nowrap; }
.review-queue__boundary { margin: 0; padding: 10px 12px; background: #f5f7fa; color: #596579; border-radius: 8px; }
.review-queue__filters { flex-wrap: wrap; }
.review-queue__filters label, .review-card__form label { display: grid; gap: 5px; font-size: .86rem; }
.review-queue__count { margin-left: auto; color: #596579; }
.review-queue__empty { padding: 32px 16px; color: #667085; text-align: center; border: 1px dashed #cbd5e1; border-radius: 10px; }
.review-card { display: grid; gap: 14px; padding: 18px; border: 1px solid #dce3ec; border-radius: 12px; background: #fff; }
.review-card__head h3 { margin: 8px 0 4px; }
.review-card__head { align-items: flex-start; }
.review-card__labels { flex-wrap: wrap; }
.review-card__priority { color: #8a4b08; background: #fff2d8; }
.review-card__type { color: #305b83; }
.review-card__status.is-pending { color: #89540a; background: #fff4dc; }
.review-card__status.is-processed { color: #17634d; background: #e3f3ed; }
.review-card__context { display: flex; gap: 16px; flex-wrap: wrap; font-size: .86rem; color: #596579; }
.review-card__signals, .review-card__values, .review-card__decision, .review-card__form, .review-card__history { padding-top: 12px; border-top: 1px solid #edf0f4; }
.review-card__warnings { padding: 10px 12px; border-radius: 8px; background: #fff7e8; color: #754a0a; }
.review-card__warnings h4 { margin: 0 0 7px; }
.review-card__warnings p { margin: 4px 0; overflow-wrap: anywhere; }
.review-card h4 { margin: 0 0 9px; }
.review-card__signals ul { margin: 0; padding-left: 20px; }
.review-card__signals li + li { margin-top: 5px; }
.review-card__values dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; margin: 0; }
.review-card__values dl div { padding: 8px 10px; background: #f7f9fb; border-radius: 7px; }
.review-card__values dt { color: #667085; font-size: .76rem; }
.review-card__values dd { margin: 3px 0 0; overflow-wrap: anywhere; }
.review-card__source { display: grid; grid-template-columns: minmax(90px, auto) 1fr; gap: 7px 12px; margin-top: 12px; font-size: .86rem; }
.review-card__source span { overflow-wrap: anywhere; white-space: pre-wrap; }
.review-card__source .is-missing { color: #a44635; }
.review-card__decision { display: grid; gap: 5px; }
.review-card__decision > span { color: #667085; font-size: .84rem; }
.review-card__decision p { margin: 0; }
.review-card__changes { display: grid; gap: 6px; }
.review-card__changes div { display: flex; gap: 10px; flex-wrap: wrap; }
.review-card__form { display: grid; gap: 12px; }
.review-card__edit-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
.review-card__history article { padding: 10px 0; border-top: 1px solid #edf0f4; }
.review-card__history p { margin: 5px 0; }
.review-queue__pagination { justify-content: center; padding-top: 4px; }
@media (max-width: 640px) {
  .review-queue__header, .review-card__head { align-items: stretch; flex-direction: column; }
  .review-card__source { grid-template-columns: 1fr; }
}
</style>
