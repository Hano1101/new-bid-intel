export const versionEntityTypes = [
  { value: 'metadata', label: '公告字段' },
  { value: 'body', label: '正文' },
  { value: 'source_file', label: '附件 / 来源文件' },
  { value: 'package', label: '采购包' },
  { value: 'bidder', label: '投标主体' },
  { value: 'award', label: '中标记录' },
  { value: 'item', label: '标的' },
]

export const versionChangeLabels = { added: '新增', removed: '删除', changed: '修改', unchanged: '未变化' }
export const versionClassificationLabels = {
  format_only: '仅格式变化', possible_semantic: '可能语义变化',
  provenance_only: '仅来源 / 定位变化', unchanged: '未变化',
}
export const versionFieldLabels = {
  project_name: '项目名称', project_number: '项目编号', procurement_unit: '采购单位',
  project_budget: '预算金额', announced_total_award: '成交金额', budget_amount: '预算金额',
  award_amount: '中标金额', package_code: '包号', package_name: '包名',
  organization_name: '主体名称', outcome: '投标结果', product_name: '标的名称',
  category: '品目', brand: '品牌', model: '型号', quantity: '数量', quantity_unit: '数量单位',
  unit_price: '单价', total_price: '总价', source_file: '来源文件', source_location: '来源定位',
  source_evidence: '来源证据', source_sha256: '来源 SHA-256', sha256: 'SHA-256',
  byte_size: '文件大小（字节）', size_bytes: '文件大小（字节）', kind: '文件用途',
  package_budget: '包预算', package_award_total: '包成交金额', '*': '整条记录',
  body: '正文', text: '正文', content: '正文', imported_at: '导入时间', consortium_members: '联合体成员',
}

export function versionFieldLabel(field) {
  const [prefix, key] = String(field || '').split('.')
  if (prefix === 'field_evidence') return `${versionFieldLabels[key] || key} · 字段来源证据`
  if (prefix === 'field_status') return `${versionFieldLabels[key] || key} · 来源状态`
  return versionFieldLabels[field] || field
}

export function versionIdentityLabel(status) {
  return {
    matched: '已匹配公告身份', new_version: '新版本', duplicate_snapshot: '相同快照',
    identity_ambiguous: '身份待确认', manual_link_required: '身份待确认 · 需要人工关联',
  }[status] || status || '身份状态未知'
}

export function versionEvidencePath(versionId) {
  if (typeof versionId !== 'string' || !/^[0-9a-f]{32}$/.test(versionId)) {
    throw new Error('版本 ID 格式无效，无法打开对应公告证据。')
  }
  return `/api/v1/notice-versions/versions/${versionId}/evidence`
}

export function filterVersionChanges(changes, filters = {}) {
  return (Array.isArray(changes) ? changes : []).filter(change =>
    (!filters.entityType || change.entity_type === filters.entityType)
    && (!filters.changeType || change.change_type === filters.changeType)
    && (!filters.classification || change.classification === filters.classification)
    && (!filters.manualOnly || change.requires_manual_confirmation),
  )
}

function positiveId(value) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isSafeInteger(number) && number > 0 ? number : null
}

// Candidate keys are matching keys, not database IDs. Only saved source IDs can
// select a candidate, and each side keeps its own notice and version context.
export function versionEvidenceTarget(change, side, context = {}) {
  if (!['before', 'after'].includes(side)) return null
  const source = change?.[`${side}_source`] || {}
  const noticeId = positiveId(source.notice_id)
    ?? positiveId(context[`${side}NoticeId`]) ?? positiveId(context.noticeId)
  if (!noticeId) return null
  const candidateType = source.candidate_type || change?.entity_type
  const itemId = candidateType === 'item' ? positiveId(source.item_id ?? source.candidate_id) : null
  return {
    notice_id: noticeId,
    ...(itemId ? { item_id: itemId } : {}),
    entity_type: change?.entity_type || 'metadata',
    source_file: source.source_file || source.filename || '',
    source_location: source.source_location || '',
    version_id: source.version_id || context[`${side}VersionId`] || null,
  }
}

export function displayVersionValue(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

export function versionSourceLabel(source) {
  if (!source) return '未保存来源定位'
  return [source.source_file || source.filename, source.source_location].filter(Boolean).join(' · ') || '未保存来源定位'
}

export function versionLabel(version, latestId) {
  const current = version?.is_latest || version?.version_id === latestId
  return `${current ? '当前版本' : '历史版本'} · ${version?.version_id || '未知'} · ${version?.imported_at || '导入时间未知'}`
}
