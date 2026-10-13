function errorMessage(payload, status) {
  return payload?.detail || payload?.message || `标准结果表下载失败（HTTP ${status}）`
}

export function normalizeNoticeIds(noticeIds) {
  if (!Array.isArray(noticeIds)) return []
  return [...new Set(noticeIds.filter((id) => id !== null && id !== undefined && String(id).trim() !== ''))]
}

export async function downloadNoticeResults(request, apiBase, noticeIds, filename = '任务三标准结果表.xlsx') {
  const ids = normalizeNoticeIds(noticeIds)
  if (!ids.length) throw new Error('本次处理没有可导出的公告结果')

  const response = await request(`${apiBase}/api/v1/notices/export-results`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ notice_ids: ids }),
  })
  if (!response.ok) {
    let payload
    try { payload = await response.json() } catch (cause) {
      if (cause?.name === 'AbortError') throw cause
      // Malformed error bodies still fall back to the HTTP status below.
    }
    throw new Error(errorMessage(payload, response.status))
  }

  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
