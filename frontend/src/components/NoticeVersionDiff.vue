<script setup>
import { computed, ref, watch } from 'vue'
import {
  displayVersionValue, filterVersionChanges, versionChangeLabels, versionClassificationLabels,
  versionEntityTypes, versionEvidenceTarget, versionFieldLabel, versionSourceLabel,
} from '../utils/versionDiff.js'

const props = defineProps({
  comparison: { type: Object, default: null },
  noticeId: { type: Number, default: null },
  beforeNoticeId: { type: Number, default: null },
  afterNoticeId: { type: Number, default: null },
  beforeVersionId: { type: String, default: '' },
  afterVersionId: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})
const emit = defineEmits(['open-evidence'])
const entityFilter = ref('')
const changeFilter = ref('')
const classificationFilter = ref('')
const manualOnly = ref(false)
const filteredChanges = computed(() => filterVersionChanges(props.comparison?.changes, {
  entityType: entityFilter.value, changeType: changeFilter.value,
  classification: classificationFilter.value, manualOnly: manualOnly.value,
}))
const summary = computed(() => props.comparison?.summary || {})

function evidenceTarget(change, side) {
  return versionEvidenceTarget(change, side, props)
}

function openEvidence(change, side) {
  const target = evidenceTarget(change, side)
  if (target) emit('open-evidence', target)
}

watch(() => props.comparison, () => {
  entityFilter.value = ''
  changeFilter.value = ''
  classificationFilter.value = ''
  manualOnly.value = false
})
</script>

<template>
  <section class="version-diff" aria-label="公告版本差异">
    <p v-if="loading" class="version-diff__empty" role="status">正在比较两个快照…</p>
    <p v-else-if="error" class="error" role="alert">{{ error }}</p>
    <p v-else-if="!comparison" class="version-diff__empty">选择两个不同版本后，点击“比较版本”查看差异。</p>
    <template v-else>
      <div class="version-diff__summary" role="status">
        <span>共 {{ summary.total ?? comparison.changes?.length ?? 0 }} 项</span>
        <span>可能语义变化 {{ summary.semantic || 0 }}</span>
        <span>仅格式变化 {{ summary.format_only || 0 }}</span>
        <span>仅来源 / 定位变化 {{ summary.provenance_only || 0 }}</span>
        <span>待人工确认 {{ summary.requires_manual_confirmation || 0 }}</span>
      </div>
      <div class="version-diff__filters">
        <label>差异类型
          <select v-model="entityFilter" aria-label="差异类型">
            <option value="">全部类型</option>
            <option v-for="type in versionEntityTypes" :key="type.value" :value="type.value">{{ type.label }}</option>
          </select>
        </label>
        <label>变化方式
          <select v-model="changeFilter" aria-label="变化方式">
            <option value="">全部变化</option>
            <option v-for="(label, key) in versionChangeLabels" :key="key" :value="key">{{ label }}</option>
          </select>
        </label>
        <label>变化性质
          <select v-model="classificationFilter" aria-label="变化性质">
            <option value="">全部性质</option>
            <option v-for="(label, key) in versionClassificationLabels" :key="key" :value="key">{{ label }}</option>
          </select>
        </label>
        <label class="version-diff__checkbox"><input v-model="manualOnly" type="checkbox" /> 仅待人工确认</label>
      </div>
      <p v-if="!comparison.changes?.length" class="version-diff__empty">两个版本没有保存的字段差异。</p>
      <p v-else-if="!filteredChanges.length" class="version-diff__empty">当前筛选下没有差异。</p>
      <article v-for="(change, index) in filteredChanges" :key="`${change.entity_type}:${change.entity_key}:${change.field}:${index}`" class="version-diff__change" :class="`is-${change.change_type}`">
        <header>
          <strong>{{ versionEntityTypes.find(type => type.value === change.entity_type)?.label || change.entity_type }} · {{ versionFieldLabel(change.field) }}</strong>
          <span class="version-diff__badge">{{ versionChangeLabels[change.change_type] || change.change_type }}</span>
          <span class="version-diff__classification" :class="`is-${change.classification}`">{{ versionClassificationLabels[change.classification] || '变化性质未知' }}</span>
          <span v-if="change.requires_manual_confirmation" class="version-diff__manual">待人工确认</span>
        </header>
        <small>关联记录：{{ change.entity_key }}</small>
        <div class="version-diff__values">
          <div v-for="side in ['before', 'after']" :key="side" class="version-diff__side">
            <h4>{{ side === 'before' ? '旧版本' : '新版本' }}</h4>
            <pre>{{ displayVersionValue(change[side]) }}</pre>
            <span>{{ versionSourceLabel(change[`${side}_source`]) }}</span>
            <p v-if="change[`${side}_source`]?.source_evidence" class="version-diff__excerpt">{{ change[`${side}_source`].source_evidence }}</p>
            <button v-if="evidenceTarget(change, side) && (side === 'before' ? change.change_type !== 'added' : change.change_type !== 'removed')" type="button" class="source-open version-diff__evidence" @click="openEvidence(change, side)">{{ side === 'before' ? '查看旧版公告证据' : '查看新版公告证据' }}</button>
          </div>
        </div>
      </article>
    </template>
  </section>
</template>

<style scoped>
.version-diff { display: grid; gap: 12px; }
.version-diff__summary, .version-diff__filters, .version-diff__change header { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.version-diff__summary { color: #596579; font-size: .84rem; padding: 10px 12px; background: #f3f6fa; border-radius: 8px; }
.version-diff__filters label { display: grid; gap: 5px; font-size: .83rem; }
.version-diff__filters .version-diff__checkbox { display: flex; gap: 5px; align-items: center; }
.version-diff__empty { padding: 22px 12px; text-align: center; color: #667085; border: 1px dashed #ccd5e1; border-radius: 8px; }
.version-diff__change { padding: 14px; display: grid; gap: 9px; border: 1px solid #dce3ec; border-left: 4px solid #91a1b6; border-radius: 9px; background: #fff; }
.version-diff__change.is-added { border-left-color: #308066; }
.version-diff__change.is-removed { border-left-color: #b65c53; }
.version-diff__change.is-changed { border-left-color: #b17b27; }
.version-diff__change > small { color: #667085; overflow-wrap: anywhere; }
.version-diff__badge, .version-diff__classification, .version-diff__manual { font-size: .75rem; padding: 4px 8px; border-radius: 999px; background: #edf2f7; }
.version-diff__manual, .version-diff__classification.is-possible_semantic { color: #86500e; background: #fff2d8; }
.version-diff__classification.is-format_only { color: #365f91; background: #eaf2fc; }
.version-diff__values { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.version-diff__side { display: grid; align-content: start; gap: 7px; min-width: 0; padding: 10px; background: #f7f9fb; border-radius: 7px; }
.version-diff__side h4, .version-diff__excerpt { margin: 0; }
.version-diff__side pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; }
.version-diff__side > span, .version-diff__excerpt { font-size: .8rem; color: #667085; white-space: pre-wrap; overflow-wrap: anywhere; }
.version-diff__evidence { justify-self: start; }
@media (max-width: 640px) { .version-diff__values { grid-template-columns: 1fr; } }
</style>
