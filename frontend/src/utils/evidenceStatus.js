const hasValue = (value) => value != null && value !== ''

export function fieldEvidenceLabel(status, value, hasEvidence = false, fieldLevel = false) {
  if (['explicitly_not_published', 'blank_in_source'].includes(status)) {
    if (hasValue(value)) return '有值 · 来源状态冲突，待核验'
    if (!hasEvidence || !fieldLevel) return '无值 · 缺少字段证据，待核验'
    return status === 'explicitly_not_published'
      ? '原文明示未公示'
      : '原文对应字段留空；不能判定为未公示'
  }
  if (status === 'unverified') {
    return hasValue(value) ? '有值 · 来源字段待核验' : '无值 · 无法判定，待核验'
  }
  if (status === 'unknown' || !status) {
    return hasValue(value) ? '有值 · 来源未核验' : '无值 · 状态未知，待核验'
  }
  if (status === 'present') {
    if (fieldLevel && hasEvidence) return '有字段来源证据'
    return hasEvidence ? '有记录级片段；未保存字段级对应关系' : '已提取 · 字段来源待核验'
  }
  return hasValue(value) ? '来源状态待核验' : '无证据 · 待核验'
}
