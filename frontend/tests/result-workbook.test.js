import assert from 'node:assert/strict'
import test from 'node:test'
import { createDatasetClient } from '../src/utils/datasets.js'
import { downloadNoticeResults, normalizeNoticeIds } from '../src/utils/resultWorkbook.js'

test('normalizeNoticeIds keeps valid unique IDs and preserves string IDs', () => {
  assert.deepEqual(normalizeNoticeIds([12, 'abc', 12, null, undefined, '', '  ']), [12, 'abc'])
  assert.deepEqual(normalizeNoticeIds(null), [])
})

test('standard result workbook export uses the dataset client and downloads the response blob', async (t) => {
  const requests = []
  const blob = new Blob(['xlsx bytes'], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const client = createDatasetClient(() => 'dataset-3', () => 0, async (url, options) => {
    const networkOptions = { ...options, credentials: 'include' }
    requests.push({ url: new URL(url), options: networkOptions })
    return {
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: new Headers({ 'Content-Type': blob.type }),
      json: async () => ({}),
      blob: async () => blob,
    }
  })
  const originalDocument = Object.getOwnPropertyDescriptor(globalThis, 'document')
  const clicked = []
  globalThis.document = {
    body: { appendChild(link) { link.remove = () => {}; } },
    createElement: () => ({ click() { clicked.push(this) } }),
  }
  t.mock.method(URL, 'createObjectURL', () => 'blob:test-result')
  t.mock.method(URL, 'revokeObjectURL', () => {})
  try {
    await downloadNoticeResults(client, 'http://api.test', [21, 21, null, 'notice-22'], 'current.xlsx')

    assert.equal(requests.length, 1)
    assert.equal(requests[0].url.pathname, '/api/v1/notices/export-results')
    assert.equal(requests[0].options.method, 'POST')
    assert.equal(requests[0].options.credentials, 'include', 'dataset fetch keeps cookies enabled')
    assert.equal(requests[0].options.headers.get('X-Dataset-ID'), 'dataset-3')
    assert.equal(requests[0].options.headers.get('Content-Type'), 'application/json')
    assert.deepEqual(JSON.parse(requests[0].options.body), { notice_ids: [21, 'notice-22'] })
    assert.equal(clicked.length, 1)
    assert.equal(clicked[0].download, 'current.xlsx')
    assert.equal(clicked[0].href, 'blob:test-result')
  } finally {
    if (originalDocument) Object.defineProperty(globalThis, 'document', originalDocument)
    else delete globalThis.document
  }
})

test('standard result workbook export rejects empty scope and surfaces API errors', async (t) => {
  let called = false
  await assert.rejects(
    downloadNoticeResults(async () => { called = true }, 'http://api.test', []),
    /没有可导出的公告结果/,
  )
  assert.equal(called, false)

  const request = async () => ({ ok: false, status: 422, json: async () => ({ detail: '公告不属于当前数据集' }) })
  await assert.rejects(downloadNoticeResults(request, 'http://api.test', [99]), /公告不属于当前数据集/)
})

test('standard result workbook export discards stale error JSON after switching A to B to A', async () => {
  let dataset = 'dataset-a'
  let version = 0
  const request = createDatasetClient(() => dataset, () => version, async () => ({
    ok: false,
    status: 404,
    json: async () => {
      dataset = 'dataset-b'
      version += 1
      dataset = 'dataset-a'
      version += 1
      return { detail: '旧数据集错误' }
    },
  }))

  await assert.rejects(
    downloadNoticeResults(request, 'http://api.test', [99]),
    { name: 'AbortError', message: '数据集已切换' },
  )
})

test('standard result workbook export keeps the HTTP fallback for malformed error JSON', async () => {
  const request = async () => ({
    ok: false,
    status: 500,
    json: async () => { throw new SyntaxError('Invalid JSON') },
  })

  await assert.rejects(downloadNoticeResults(request, 'http://api.test', [99]), /HTTP 500/)
})
