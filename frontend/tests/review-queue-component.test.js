import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive, ref } from 'vue'

// Exercise the real setup/actions without a browser or DOM. Template bindings are
// checked separately; these tests do not claim browser interaction coverage.
const sourceUrl = new URL('../src/components/ReviewQueue.vue', import.meta.url)
async function loadComponent() {
  const { descriptor } = parse(await readFile(sourceUrl, 'utf8'))
  const script = compileScript(descriptor, { id: 'review-queue-component-test' }).content.replace(
    /from (['"])([^'"]+)\1/g,
    (_, quote, specifier) => `from ${quote}${specifier.startsWith('.') ? new URL(specifier, sourceUrl).href : import.meta.resolve(specifier)}${quote}`,
  )
  return (await import(`data:text/javascript;base64,${Buffer.from(script).toString('base64')}`)).default
}
const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  setText() {}, setElementText() {}, insert() {}, remove() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null,
})
async function settle() {
  for (let index = 0; index < 8; index += 1) {
    await Promise.resolve()
    await nextTick()
  }
}
async function mount(fetchImpl) {
  const component = { ...await loadComponent(), render: () => null }
  const props = reactive({ apiBase: 'http://api.test', datasetId: 'dataset-a', fetchImpl })
  const instance = ref(null)
  const emitted = []
  const app = renderer.createApp({
    render: () => h(component, { ...props, ref: instance, onOpenNotice: value => emitted.push(value) }),
  })
  app.mount({})
  await settle()
  return { props, state: instance.value.$.setupState, emitted, unmount: () => app.unmount() }
}
const response = (payload, status = 200) => ({
  ok: status >= 200 && status < 300, status, headers: new Headers(), json: async () => payload,
})
function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function candidate(id = 1, type = 'item', epoch = 1) {
  const values = type === 'item'
    ? { package_code: 'P1', product_name: '设备甲', category: null, brand: null, model: null,
        quantity: '2', quantity_unit: null, unit_price: '10', total_price: '25' }
    : type === 'bid'
      ? { package_code: 'P1', organization_name: '供应商甲', outcome: 'unknown' }
      : { package_code: 'P1', organization_name: '供应商甲', award_amount: '100' }
  return { candidate_id: id, candidate_type: type, candidate_epoch: epoch, notice_id: 7,
    ...values, values, status: 'pending', reasons: [{ code: 'source_evidence_missing', detail: '缺少来源片段' }],
    priority: { rank: 1, label: '核对来源' } }
}
const queueResult = (items, url, total = items.length) => ({
  items, total, status: url.searchParams.get('status') || 'pending',
  limit: Number(url.searchParams.get('limit') || 20), offset: Number(url.searchParams.get('offset') || 0),
})
const event = (action = 'accepted', id = 1) => ({ id, action, actor: 'reviewer', created_at: '2026-10-10T00:00:00Z',
  reason: '核对来源', candidate_epoch: 1, changes: {} })

test('queue requests preserve dataset headers and status/type/page filters, and evidence actions emit the candidate', async () => {
  const requests = []
  const row = candidate()
  const view = await mount(async (url, options) => {
    const parsed = new URL(url)
    requests.push({ url: parsed, options })
    return response(queueResult([row], parsed, 43))
  })
  try {
    assert.equal(view.state.queue.items[0].candidate_id, 1)
    await view.state.changePage(20)
    assert.equal(view.state.pageNumber, 2)
    assert.equal(view.state.pageCount, 3)
    view.state.startDecision(row, 'accepted')
    view.state.statusFilter = 'processed'
    view.state.typeFilter = 'bid'
    await view.state.changeFilter()
    assert.equal(view.state.queue.offset, 0)
    assert.equal(view.state.draft, null)
    const latest = requests.at(-1)
    assert.equal(latest.url.searchParams.get('status'), 'processed')
    assert.equal(latest.url.searchParams.get('candidate_type'), 'bid')
    assert.equal(latest.url.searchParams.get('limit'), '20')
    assert.equal(latest.url.searchParams.get('offset'), '0')
    assert.ok(requests.every(request => request.options.headers.get('X-Dataset-ID') === 'dataset-a'))
    view.state.openEvidence(row)
    assert.deepEqual(view.emitted, [{ noticeId: 7, itemId: 1 }])
  } finally { view.unmount() }
})

test('accepted, corrected and rejected actions send epochs, reasons and only the one changed field', async () => {
  const sent = []
  const rows = [candidate(1), candidate(2, 'bid'), candidate(3, 'award')]
  const view = await mount(async (url, options) => {
    const parsed = new URL(url)
    if (options.method === 'POST') {
      const payload = JSON.parse(options.body)
      sent.push({ url: parsed, options, payload })
      return response(event(payload.action), 201)
    }
    return response(queueResult(rows, parsed))
  })
  try {
    for (const [index, action] of ['accepted', 'corrected', 'rejected'].entries()) {
      view.state.startDecision(rows[index], action)
      view.state.draft.reason = `理由 ${action}`
      if (action === 'corrected') view.state.draft.values.organization_name = '供应商乙'
      await view.state.submitDecision(rows[index])
      assert.equal(view.state.draft, null)
      assert.match(view.state.message, /reviewer/)
    }
    assert.deepEqual(sent.map(request => request.payload), [
      { action: 'accepted', reason: '理由 accepted', candidate_epoch: 1 },
      { action: 'corrected', reason: '理由 corrected', candidate_epoch: 1,
        corrected_values: { organization_name: '供应商乙' } },
      { action: 'rejected', reason: '理由 rejected', candidate_epoch: 1 },
    ])
    assert.deepEqual(sent.map(request => request.url.pathname), [
      '/api/v1/review-queue/item/1/decisions', '/api/v1/review-queue/bid/2/decisions',
      '/api/v1/review-queue/award/3/decisions',
    ])
    for (const request of sent) {
      assert.equal(request.options.headers.get('X-Dataset-ID'), 'dataset-a')
      assert.equal(request.options.headers.get('Content-Type'), 'application/json')
    }
  } finally { view.unmount() }
})

test('a one-field item correction omits unchanged blank fields, and an unchanged correction sends no request', async () => {
  const sent = []
  const row = candidate()
  const view = await mount(async (url, options) => {
    const parsed = new URL(url)
    if (options.method === 'POST') {
      sent.push(JSON.parse(options.body))
      return response(event('corrected'), 201)
    }
    return response(queueResult([row], parsed))
  })
  try {
    view.state.startDecision(row, 'corrected')
    view.state.draft.reason = '核对原文'
    await view.state.submitDecision(row)
    assert.match(view.state.error, /至少修改一个字段/)
    assert.equal(sent.length, 0)
    view.state.draft.values.product_name = '设备乙'
    await view.state.submitDecision(row)
    assert.deepEqual(sent[0].corrected_values, { product_name: '设备乙' })
  } finally { view.unmount() }
})

test('duplicate 409 and network failure preserve the draft and expose the actionable error', async () => {
  const row = candidate()
  let failure = 'duplicate'
  const view = await mount(async (url, options) => {
    if (options.method === 'POST') {
      if (failure === 'duplicate') return response({ detail: '检测到重复决定；请刷新复核历史' }, 409)
      throw new Error('连接中断')
    }
    return response(queueResult([row], new URL(url)))
  })
  try {
    view.state.startDecision(row, 'accepted')
    view.state.draft.reason = '核对原文'
    await view.state.submitDecision(row)
    assert.match(view.state.error, /重复决定/)
    assert.equal(view.state.draft.reason, '核对原文')
    assert.equal(view.state.busy, false)
    failure = 'network'
    await view.state.submitDecision(row)
    assert.equal(view.state.error, '连接中断')
    assert.equal(view.state.draft.action, 'accepted')
    assert.equal(view.state.busy, false)
  } finally { view.unmount() }
})

test('late queue JSON after A to B to A cannot replace the new dataset queue or finish its loading', async () => {
  const oldJson = deferred()
  const newQueue = deferred()
  let count = 0
  const view = await mount(async url => {
    count += 1
    if (count === 1) return { ...response({}), json: () => oldJson.promise }
    if (count === 3) return newQueue.promise
    return response(queueResult([candidate(2)], new URL(url)))
  })
  try {
    view.props.datasetId = 'dataset-b'
    await settle()
    assert.equal(view.state.queue.items[0].candidate_id, 2)
    view.props.datasetId = 'dataset-a'
    await settle()
    oldJson.resolve(queueResult([candidate(99)], new URL('http://api.test')))
    await settle()
    assert.equal(view.state.queue.items.length, 0)
    assert.equal(view.state.busy, true)
    newQueue.resolve(response(queueResult([candidate(3)], new URL('http://api.test'))))
    await settle()
    assert.equal(view.state.queue.items[0].candidate_id, 3)
    assert.equal(view.state.error, '')
  } finally { view.unmount() }
})

test('a late decision after dataset switching does not write a message, clear the new draft or stop its loading', async () => {
  const oldDecision = deferred()
  const newQueue = deferred()
  const row = candidate()
  const requests = []
  const view = await mount(async (url, options) => {
    const dataset = options.headers.get('X-Dataset-ID')
    requests.push(dataset)
    if (options.method === 'POST') return oldDecision.promise
    if (dataset === 'dataset-b') return newQueue.promise
    return response(queueResult([row], new URL(url)))
  })
  try {
    view.state.startDecision(row, 'accepted')
    view.state.draft.reason = '旧库理由'
    const pending = view.state.submitDecision(row)
    view.props.datasetId = 'dataset-b'
    await settle()
    oldDecision.resolve(response(event(), 201))
    await pending
    assert.equal(view.state.message, '')
    assert.equal(view.state.busy, true)
    assert.equal(view.state.queue.items.length, 0)
    const newRow = candidate(2)
    newQueue.resolve(response(queueResult([newRow], new URL('http://api.test'))))
    await settle()
    view.state.startDecision(newRow, 'rejected')
    assert.equal(view.state.draft.key, 'item:2:1')
    assert.deepEqual(requests, ['dataset-a', 'dataset-a', 'dataset-b'])
  } finally { view.unmount() }
})

test('handling the last candidate on page two refetches the last valid page instead of leaving an empty offset', async () => {
  let total = 21
  const offsets = []
  const view = await mount(async (url, options) => {
    const parsed = new URL(url)
    if (options.method === 'POST') {
      total = 20
      return response(event(), 201)
    }
    const offset = Number(parsed.searchParams.get('offset') || 0)
    offsets.push(offset)
    const items = offset >= total ? [] : [candidate(offset + 1)]
    return response(queueResult(items, parsed, total))
  })
  try {
    await view.state.changePage(20)
    const row = view.state.queue.items[0]
    view.state.startDecision(row, 'accepted')
    view.state.draft.reason = '已核对'
    await view.state.submitDecision(row)
    assert.deepEqual(offsets, [0, 20, 20, 0])
    assert.equal(view.state.queue.offset, 0)
    assert.equal(view.state.queue.total, 20)
    assert.equal(view.state.queue.items[0].candidate_id, 1)
    assert.equal(view.state.pageNumber, 1)
  } finally { view.unmount() }
})

test('refresh reloads opened same-epoch history, clears closed caches and displays history failures', async () => {
  const rows = [candidate(1), candidate(2)]
  let historyId = 1
  let failHistory = false
  const historyRequests = []
  const view = await mount(async (url, options) => {
    const parsed = new URL(url)
    if (parsed.pathname.endsWith('/history')) {
      historyRequests.push({ url: parsed, options })
      if (failHistory) return response({ detail: '历史暂不可读取' }, 503)
      return response({ events: [event('accepted', historyId)] })
    }
    return response(queueResult(rows, parsed))
  })
  try {
    await view.state.toggleHistory(rows[1])
    await view.state.toggleHistory(rows[1])
    await view.state.toggleHistory(rows[0])
    assert.equal(view.state.historyByKey['item:1:1'].events[0].id, 1)
    historyId = 2
    await view.state.refresh()
    assert.equal(view.state.historyByKey['item:1:1'].events[0].id, 2)
    assert.equal(view.state.historyByKey['item:2:1'], undefined)
    assert.ok(historyRequests.every(request => request.options.headers.get('X-Dataset-ID') === 'dataset-a'))
    failHistory = true
    await view.state.refresh()
    assert.equal(view.state.historyByKey['item:1:1'], undefined)
    assert.equal(view.state.historyErrors['item:1:1'], '历史暂不可读取')
    assert.equal(view.state.busy, false)
    failHistory = false
    await view.state.refresh()
    assert.equal(view.state.historyErrors['item:1:1'], undefined)
    assert.equal(view.state.historyByKey['item:1:1'].events[0].id, 2)
    const source = await readFile(sourceUrl, 'utf8')
    assert.ok(source.includes('v-if="historyErrors[rowKey(row)]" class="error" role="alert"'))
    assert.ok(source.includes('v-else-if="!historyByKey[rowKey(row)]"'))
    assert.ok(source.includes('historyByKey[rowKey(row)]?.events || []'))
  } finally { view.unmount() }
})

test('history returned after switching datasets cannot repopulate a cleared cache', async () => {
  const pendingHistory = deferred()
  const row = candidate()
  const view = await mount(async (url, options) => {
    const parsed = new URL(url)
    if (parsed.pathname.endsWith('/history')) return pendingHistory.promise
    return response(queueResult([options.headers.get('X-Dataset-ID') === 'dataset-a' ? row : candidate(2)], parsed))
  })
  try {
    const pending = view.state.toggleHistory(row)
    view.props.datasetId = 'dataset-b'
    await settle()
    pendingHistory.resolve(response({ events: [event()] }))
    await pending
    assert.deepEqual(view.state.historyByKey, {})
    assert.deepEqual(view.state.historyErrors, {})
    assert.equal(view.state.historyOpen, '')
    assert.equal(view.state.queue.items[0].candidate_id, 2)
  } finally { view.unmount() }
})
