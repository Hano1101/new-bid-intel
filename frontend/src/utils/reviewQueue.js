export function reviewPackageLabel(value) {
  if (!value) return '未保存'
  return value === 'default' ? 'default（系统默认值）' : value
}

export function reviewSourceEvidence(row) {
  const excerpt = row?.source_evidence
  return typeof excerpt === 'string' && excerpt.trim() ? excerpt : '无来源片段'
}

export function hasReviewSourceEvidence(row) {
  return typeof row?.source_evidence === 'string' && Boolean(row.source_evidence.trim())
}

export function reviewWarningDetails(row) {
  return (row?.reasons || [])
    .filter(reason => reason.code === 'parsing_warning')
    .map(reason => reason.detail)
}

export function reviewEvidenceTarget(row) {
  return {
    noticeId: row?.notice_id ?? null,
    itemId: row?.candidate_type === 'item' ? row.candidate_id : null,
  }
}

export function reviewCorrectionValues(draftValues, originalValues) {
  const corrections = {}
  for (const [field, draftValue] of Object.entries(draftValues || {})) {
    const originalValue = originalValues?.[field]
    const originalText = originalValue == null ? '' : String(originalValue).trim()
    const draftText = draftValue == null ? '' : String(draftValue).trim()
    if (draftText === originalText) continue
    corrections[field] = draftText === '' ? null : draftText
  }
  return corrections
}

export function reviewCandidateKey(row) {
  return `${row?.candidate_type}:${row?.candidate_id}:${row?.candidate_epoch}`
}
