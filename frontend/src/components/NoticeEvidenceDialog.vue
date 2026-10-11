<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { formatAmount } from '../utils/amountPolicy.js'
import { fieldEvidenceLabel } from '../utils/evidenceStatus.js'

const props = defineProps({
  notice: { type: Object, default: null },
  initialItemId: { type: Number, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

defineEmits(['close'])

const selectedEvidence = ref(null)
const dialogRef = ref(null)
const fragmentDialogRef = ref(null)
let dialogReturnFocusElement = null
let fragmentReturnFocusElement = null
let lockedScrollY = 0
let lockedScrollX = 0
let previousBodyStyles = null
const bodyLockProperties = ['position', 'top', 'left', 'right', 'width', 'overflow', 'padding-right']
const itemFields = [
  { key: 'product_name', label: '产品 / 服务名称' },
  { key: 'category', label: '品目' },
  { key: 'brand', label: '品牌' },
  { key: 'model', label: '规格型号' },
  { key: 'quantity', label: '数量' },
  { key: 'unit_price', label: '单价' },
  { key: 'total_price', label: '总价' },
]
const metadataFields = [
  { key: 'project_name', label: '项目名称' },
  { key: 'project_number', label: '项目编号' },
  { key: 'procurement_unit', label: '采购单位' },
  { key: 'project_budget', label: '项目预算' },
  { key: 'announced_total_award', label: '公告金额' },
]
watch(() => [props.notice?.notice_id, props.initialItemId], () => {
  selectedEvidence.value = null
  const item = props.notice?.items?.find(row => row.id === props.initialItemId)
  if (item?.source_evidence) openEvidence(item, '标的候选')
})

function isDialogOpen() {
  return Boolean(props.loading || props.error || props.notice)
}

function lockPageScroll() {
  if (typeof window === 'undefined' || typeof document === 'undefined') return
  const body = document.body
  lockedScrollY = window.scrollY || window.pageYOffset || 0
  lockedScrollX = window.scrollX || window.pageXOffset || 0
  previousBodyStyles = Object.fromEntries(bodyLockProperties.map(property => [property, {
    value: body.style.getPropertyValue(property),
    priority: body.style.getPropertyPriority(property),
  }]))
  body.style.position = 'fixed'
  body.style.top = `-${lockedScrollY}px`
  body.style.left = `-${lockedScrollX}px`
  body.style.right = '0'
  body.style.width = '100%'
  body.style.overflow = 'hidden'
  const scrollbarWidth = Math.max(0, window.innerWidth - document.documentElement.clientWidth)
  if (scrollbarWidth) body.style.paddingRight = `${scrollbarWidth}px`
}

function unlockPageScroll() {
  if (!previousBodyStyles) return
  for (const property of bodyLockProperties) {
    const previous = previousBodyStyles[property]
    if (previous.value) document.body.style.setProperty(property, previous.value, previous.priority)
    else document.body.style.removeProperty(property)
  }
  previousBodyStyles = null
  if (typeof window !== 'undefined') window.scrollTo(lockedScrollX, lockedScrollY)
}

function trapDialogTab(event, dialogReference) {
  if (event.key !== 'Tab') return
  const dialog = dialogReference.value
  if (!dialog) return
  const focusable = [...dialog.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
  if (!focusable.length) {
    event.preventDefault()
    dialog.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

watch(isDialogOpen, async (isOpen, wasOpen) => {
  if (isOpen) {
    if (!wasOpen) {
      dialogReturnFocusElement = typeof document === 'undefined' ? null : document.activeElement
      lockPageScroll()
    }
    await nextTick()
    dialogRef.value?.focus()
    return
  }

  if (wasOpen) {
    selectedEvidence.value = null
    unlockPageScroll()
    await nextTick()
    if (dialogReturnFocusElement?.isConnected) dialogReturnFocusElement.focus()
    dialogReturnFocusElement = null
  }
})

watch(selectedEvidence, async (evidence, previousEvidence) => {
  if (evidence) {
    await nextTick()
    fragmentDialogRef.value?.focus()
  } else if (previousEvidence) {
    await nextTick()
    if (isDialogOpen() && fragmentReturnFocusElement?.isConnected) fragmentReturnFocusElement.focus()
    fragmentReturnFocusElement = null
  }
})

onBeforeUnmount(() => {
  unlockPageScroll()
})

function openEvidence(record, title) {
  if (!selectedEvidence.value && typeof document !== 'undefined') {
    fragmentReturnFocusElement = document.activeElement
  }
  selectedEvidence.value = {
    title,
    source_file: record.source_file || '',
    source_location: record.source_location || '',
    source_evidence: record.source_evidence || '',
    source_sha256: record.source_sha256 || '',
    source_hash_status: record.source_hash_status || 'not_saved',
    source_hash_provenance_status: record.source_hash_provenance_status,
  }
}

function closeEvidenceDialog() {
  selectedEvidence.value = null
}

function sourceHashLabel(record) {
  if (record.source_hash_status === 'ambiguous') return '同名来源文件哈希有歧义，无法可靠关联到此候选'
  if (record.source_hash_provenance_status === 'unavailable') return '历史原始文件不可用，未保存可核验的 SHA-256'
  return record.source_sha256 || '未保存'
}

function showValue(value) {
  if (value == null || value === '') return '—'
  return String(value)
}

function showAmount(value) {
  return formatAmount(value)
}

function packageLabel(value) {
  if (!value) return '无证据'
  return value === 'default' ? 'default（系统默认，非原文包号）' : value
}

function metadataEvidence(field) {
  return props.notice?.metadata_evidence?.[field.key] || null
}

function metadataEvidenceLabel(field) {
  const evidence = metadataEvidence(field)
  return fieldEvidenceLabel(
    props.notice?.metadata_field_status?.[field.key],
    props.notice?.metadata?.[field.key],
    Boolean(evidence?.source_evidence),
    true,
  )
}

function openMetadataEvidence(field) {
  const evidence = metadataEvidence(field)
  if (evidence?.source_evidence) openEvidence(evidence, field.label)
}

function valueEvidenceLabel(field, item) {
  const fieldEvidence = item.field_evidence?.[field.key]
  return fieldEvidenceLabel(item.field_status?.[field.key], item[field.key],
    Boolean(fieldEvidence?.source_evidence || item.source_evidence), Boolean(fieldEvidence))
}
</script>

<template>
  <Teleport to="body">
    <div v-if="loading || error || notice" class="evidence-overlay" @click.self="$emit('close')" @keydown.esc="$emit('close')" @keydown.tab="trapDialogTab($event, dialogRef)">
      <section ref="dialogRef" class="evidence-dialog" role="dialog" aria-modal="true" aria-labelledby="evidence-title" tabindex="-1">
      <header class="evidence-dialog-head">
        <div>
          <p class="eyebrow">SOURCE EVIDENCE</p>
          <h2 id="evidence-title">公告详情与原文证据</h2>
          <p v-if="notice" class="evidence-subtitle">公告 #{{ notice.notice_id }} · {{ notice.metadata.project_name || notice.metadata.project_number || '未保存公告名称' }}</p>
        </div>
        <button type="button" class="evidence-close" aria-label="关闭公告详情" @click="$emit('close')">×</button>
      </header>

      <p v-if="loading" class="evidence-loading">正在读取公告来源与候选记录…</p>
      <p v-else-if="error" class="error" role="alert">{{ error }}</p>

      <template v-else-if="notice">
        <div class="evidence-boundary">
          当前页面只展示已保存的来源证据。只有原文明写未公示才会标为明确未公示；空单元格和旧记录空值显示为待核验。记录级片段不代表每个字段的精确引用。
        </div>

        <section class="evidence-section">
          <h3>公告字段</h3>
          <div class="evidence-metadata-grid">
            <article v-for="field in metadataFields" :key="field.key">
              <small>{{ field.label }}</small>
              <strong>{{ ['project_budget', 'announced_total_award'].includes(field.key) ? showAmount(notice.metadata[field.key]) : showValue(notice.metadata[field.key]) }}</strong>
              <span :class="metadataEvidence(field)?.source_evidence ? 'evidence-present' : 'evidence-missing'">{{ metadataEvidenceLabel(field) }}</span>
              <button v-if="metadataEvidence(field)?.source_evidence" type="button" class="source-open" @click="openMetadataEvidence(field)">查看字段来源片段</button>
            </article>
          </div>
        </section>

        <section class="evidence-section">
          <h3>来源公告与附件 <span>{{ notice.source_files.length }} 个文件</span></h3>
          <div v-if="notice.source_files.length" class="evidence-source-list">
            <article v-for="source in notice.source_files" :key="`${source.source_file}:${source.sha256 || 'unknown'}`">
              <strong>{{ source.source_file }}</strong>
              <small>原始文件 SHA-256</small>
              <code>{{ source.sha256 || '未保存' }}</code>
              <span>{{ source.file_available ? '原始文件可打开' : source.hash_provenance_status === 'unavailable' ? '原始文件字节未留存，历史 SHA-256 不可用' : '原始文件字节未留存；可打开候选中保存的证据片段' }}</span>
            </article>
          </div>
          <p v-else class="evidence-empty">无保存的来源文件清单</p>
        </section>

        <section class="evidence-section">
          <h3>采购包 <span>{{ notice.packages.length }} 个</span></h3>
          <div v-if="notice.packages.length" class="evidence-package-list">
            <article v-for="pkg in notice.packages" :key="pkg.id">
              <strong>包号：{{ packageLabel(pkg.package_code) }}</strong>
              <span>包名：{{ pkg.package_name || '未保存' }}</span>
              <small>包号未单独保存字段级证据；请查看关联候选记录片段。</small>
            </article>
          </div>
          <p v-else class="evidence-empty">没有保存采购包记录</p>
        </section>

        <section class="evidence-section">
          <h3>标的候选 <span>{{ notice.items.length }} 条</span></h3>
          <article v-for="item in notice.items" :key="`item-${item.id}`" class="evidence-record">
            <header>
              <strong>{{ item.product_name || '未识别名称' }}</strong>
              <span>包号：{{ packageLabel(item.package_code) }}</span>
            </header>
            <div class="evidence-field-grid">
              <div v-for="field in itemFields" :key="field.key">
                <small>{{ field.label }}</small>
                <strong>{{ ['unit_price', 'total_price'].includes(field.key) ? showAmount(item[field.key]) : showValue(item[field.key]) }}</strong>
                <span :class="item.source_evidence ? 'evidence-present' : 'evidence-missing'">
                  {{ valueEvidenceLabel(field, item) }}
                </span>
                <button v-if="item.field_evidence?.[field.key]?.source_evidence" type="button" class="source-open" @click="openEvidence(item.field_evidence[field.key], field.label)">查看字段来源</button>
              </div>
            </div>
            <div class="evidence-record-source">
              <span>来源：{{ item.source_file || '未保存' }}</span>
              <span>定位：{{ item.source_location || '无定位' }}</span>
              <button v-if="item.source_evidence" type="button" class="source-open" @click="openEvidence(item, '标的候选')">查看对应证据片段</button>
              <span v-else class="evidence-missing">无证据</span>
            </div>
          </article>
          <p v-if="!notice.items.length" class="evidence-empty">没有保存标的候选</p>
        </section>

        <section class="evidence-section">
          <h3>投标方 <span>{{ notice.bidders.length }} 条</span></h3>
          <article v-for="bidder in notice.bidders" :key="`bidder-${bidder.id}`" class="evidence-relation">
            <div>
              <strong>{{ bidder.organization_name }}</strong>
              <span>{{ bidder.outcome }} · 包号 {{ packageLabel(bidder.package_code) }}</span>
              <small v-if="bidder.consortium_members?.length">联合体成员：{{ bidder.consortium_members.join('、') }}</small>
              <small>来源：{{ bidder.source_file || '未保存' }} · {{ bidder.source_location || '无定位' }}</small>
            </div>
            <button v-if="bidder.source_evidence" type="button" class="source-open" @click="openEvidence(bidder, '投标方记录')">查看证据片段</button>
            <span v-else class="evidence-missing">无证据</span>
          </article>
          <p v-if="!notice.bidders.length" class="evidence-empty">没有保存投标方记录</p>
        </section>

        <section class="evidence-section">
          <h3>中标记录 <span>{{ notice.awards.length }} 条</span></h3>
          <article v-for="award in notice.awards" :key="`award-${award.id}`" class="evidence-relation">
            <div>
              <strong>{{ award.organization_name }}</strong>
              <span>中标金额：{{ showAmount(award.award_amount) }} · 包号 {{ packageLabel(award.package_code) }}</span>
              <small>来源：{{ award.source_file || '未保存' }} · {{ award.source_location || '无定位' }}</small>
            </div>
            <button v-if="award.source_evidence" type="button" class="source-open" @click="openEvidence(award, '中标记录')">查看证据片段</button>
            <span v-else class="evidence-missing">无证据</span>
          </article>
          <p v-if="!notice.awards.length" class="evidence-empty">没有保存中标记录</p>
        </section>

        <section class="evidence-section">
          <h3>解析 / OCR 警告 <span>{{ notice.warnings.length }} 条</span></h3>
          <div v-if="notice.warnings.length" class="warning-list">
            <p v-for="(warning, index) in notice.warnings" :key="`${index}-${warning}`">{{ warning }}</p>
          </div>
          <p v-else class="evidence-empty">本次记录保存的警告数为 0</p>
        </section>
      </template>

      </section>
    </div>
  </Teleport>
  <Teleport to="body">
      <div v-if="selectedEvidence" class="source-fragment-overlay" @click.self="closeEvidenceDialog" @keydown.esc="closeEvidenceDialog" @keydown.tab="trapDialogTab($event, fragmentDialogRef)">
        <section ref="fragmentDialogRef" class="source-fragment-dialog" role="dialog" aria-modal="true" aria-labelledby="fragment-title" tabindex="-1">
          <header>
            <div><p class="eyebrow">SAVED SOURCE EXCERPT</p><h3 id="fragment-title">{{ selectedEvidence.title }} · 对应证据片段</h3></div>
            <button type="button" class="evidence-close" aria-label="关闭证据片段" @click="closeEvidenceDialog">×</button>
          </header>
          <p><strong>来源文件：</strong>{{ selectedEvidence.source_file || '未保存' }}</p>
          <p><strong>原文定位：</strong>{{ selectedEvidence.source_location || '无定位' }}</p>
          <p><strong>SHA-256：</strong>{{ sourceHashLabel(selectedEvidence) }}</p>
          <pre>{{ selectedEvidence.source_evidence || '无证据' }}</pre>
          <small>显示系统已保存的来源片段；表格字段片段保留表头和单元格文本，文本行号指解析正文。页面不推断未保存的页码或字段级引用，已保存哈希不代表原件仍可打开。</small>
        </section>
      </div>
  </Teleport>
</template>
