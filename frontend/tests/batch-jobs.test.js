import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive, ref } from 'vue'

async function loadComponent() {
  const sourceUrl = new URL('../src/components/BatchJobs.vue', import.meta.url)
  const { descriptor } = parse(await readFile(sourceUrl, 'utf8'))
  const script = compileScript(descriptor, { id: 'BatchJobs' }).content.replace(
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

async function mount(props) {
  const component = await loadComponent()
  const renderable = { ...component, render: () => null }
  const currentProps = reactive(props)
  const instance = ref(null)
  const app = renderer.createApp({
    render: () => h(renderable, { ...currentProps, ref: instance }),
  })
  app.mount({})
  return { props: currentProps, state: instance.value.$.setupState, unmount: () => app.unmount() }
}

const response = (payload, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  statusText: status === 200 ? 'OK' : 'Service Unavailable',
  headers: new Headers({ 'Content-Type': 'application/json' }),
  json: async () => payload,
})

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

const directory = (directoryId) => ({
  directory_id: directoryId,
  directory_name: directoryId || 'intake',
  parent_directory_id: directoryId ? '' : null,
  directories: [],
})

const preview = {
  directory_id: 'batch',
  preflight_fingerprint: 'fingerprint-001',
  directory_name: 'batch',
  html_count: 2,
  paired_archive_count: 2,
  notices_with_attachments: 1,
  unpaired_material_count: 1,
  unpaired_materials: ['orphan.zip'],
  unpaired_materials_truncated: false,
  notices: [
    { html: 'notice-a.html', attachments: ['notice-a.zip', 'notice-a.rar'] },
    { html: 'notice-b.htm', attachments: [] },
  ],
  notices_truncated: false,
  directory_bytes: 12345,
  directory_file_count: 3,
  skipped_symlink_count: 0,
  invalid_material_count: 0,
  can_start: true,
  top_level_scan_only: true,
  scan_note: '任务只扫描当前目录顶层的公告及附件，不会递归处理子目录。',
}

async function settle() {
  await Promise.resolve()
  await nextTick()
  await Promise.resolve()
  await nextTick()
}

test('directory navigation and preflight state feed the visible preview before creating a job', async (t) => {
  const requests = []
  t.mock.method(globalThis, 'fetch', async (url, options = {}) => {
    const parsed = new URL(url)
    requests.push({ url: parsed, options })
    if (parsed.pathname.endsWith('/directories')) {
      const directoryId = parsed.searchParams.get('directory_id')
      return response(directoryId === 'batch'
        ? { directory_id: 'batch', directory_name: 'batch', parent_directory_id: '', directories: [] }
        : { directory_id: '', directory_name: 'intake', parent_directory_id: null, directories: [{ name: 'batch', directory_id: 'batch' }] })
    }
    if (parsed.pathname.endsWith('/preflight')) return response(preview)
    if (parsed.pathname.endsWith('/jobs') && options.method === 'POST') return response({ id: 'job-one' }, 202)
    if (parsed.pathname.endsWith('/jobs')) return response([])
    throw new Error(`Unexpected request ${parsed.pathname}`)
  })
  const view = await mount({ apiBase: 'http://api.test', datasetId: 'dataset-a' })
  try {
    await settle()
    await view.state.openBrowser('')
    assert.equal(view.state.browser.directory_id, '')
    await view.state.enterDirectory('batch')
    assert.equal(view.state.browser.directory_id, 'batch')
    assert.equal(view.state.browser.parent_directory_id, '')
    await view.state.enterDirectory(view.state.browser.parent_directory_id)
    assert.equal(view.state.browser.directory_id, '')
    await view.state.enterDirectory('batch')
    await view.state.checkDirectory()

    assert.equal(view.state.preflight.html_count, 2)
    assert.equal(view.state.preflight.paired_archive_count, 2)
    assert.deepEqual(view.state.preflight.notices[0], {
      html: 'notice-a.html', attachments: ['notice-a.zip', 'notice-a.rar'],
    })
    assert.deepEqual(view.state.preflight.unpaired_materials, ['orphan.zip'])
    assert.equal(view.state.formatBytes(view.state.preflight.directory_bytes), '12.1 KB')

    const template = (await readFile(new URL('../src/components/BatchJobs.vue', import.meta.url), 'utf8'))
    for (const visibleBinding of [
      '顶层 HTML/HTM：<strong>{{ preflight.html_count }}</strong>',
      '配对的同名 ZIP/RAR/7z：<strong>{{ preflight.paired_archive_count }}</strong>',
      '未配对压缩材料：<strong>{{ preflight.unpaired_material_count }}</strong>',
      '目录总字节数：<strong>{{ preflight.directory_bytes.toLocaleString() }} B</strong>',
      '{{ notice.html }}', "notice.attachments.join('、')", '{{ preflight.scan_note }}',
      'directoryError && !browserOpen',
    ]) assert.ok(template.includes(visibleBinding), `template displays ${visibleBinding}`)

    await view.state.create()
    assert.ok(!requests.some(({ options }) => options.method === 'POST'), 'preflight alone does not confirm the directory')
    view.state.chooseDirectory()
    assert.equal(view.state.selectedDirectory.directoryId, 'batch')
    await view.state.create()
    await settle()
    const created = requests.find(({ url, options }) => url.pathname.endsWith('/jobs') && options.method === 'POST')
    assert.ok(created)
    assert.deepEqual(JSON.parse(created.options.body), {
      directory_id: 'batch', preflight_fingerprint: 'fingerprint-001', mode: 'hybrid', ocr: true,
    })
    assert.equal(created.options.headers.get('X-Dataset-ID'), 'dataset-a')
    await view.state.refresh()
    assert.ok(requests.some(({ url, options }) => url.pathname.endsWith('/jobs') && options.method !== 'POST'),
      'initial load, polling refresh, and post-create refresh use the dataset client')
    assert.ok(requests.every(({ options }) => options.credentials === 'include'),
      'list, directory browsing, preflight, create, and refresh requests include session cookies')
  } finally { view.unmount() }
})

test('directory browser and preflight failures remain visible in the error state', async (t) => {
  let configured = false
  let failPreflight = false
  t.mock.method(globalThis, 'fetch', async (url) => {
    const parsed = new URL(url)
    if (parsed.pathname.endsWith('/directories')) {
      if (!configured) return {
        ...response({}, 503),
        json: async () => { throw new SyntaxError('non-JSON error') },
      }
      return response({ directory_id: '', directory_name: 'intake', parent_directory_id: null, directories: [] })
    }
    if (parsed.pathname.endsWith('/preflight') && failPreflight) {
      return response({ detail: '目录暂不可读取' }, 400)
    }
    if (parsed.pathname.endsWith('/preflight')) return response({ ...preview, directory_id: '' })
    if (parsed.pathname.endsWith('/jobs')) return response([])
    throw new Error(`Unexpected request ${parsed.pathname}`)
  })
  const view = await mount({ apiBase: 'http://api.test', datasetId: 'dataset-a' })
  try {
    await settle()
    await view.state.openBrowser('')
    assert.match(view.state.directoryError, /HTTP 503/)

    configured = true
    await view.state.openBrowser('')
    await view.state.checkDirectory()
    assert.equal(view.state.preflight.html_count, 2)
    failPreflight = true
    await view.state.checkDirectory()
    assert.match(view.state.directoryError, /目录暂不可读取/)
    assert.equal(view.state.preflight, null)
  } finally { view.unmount() }
})

test('latest navigation wins and an older request cannot clear current loading or errors', async (t) => {
  const pending = new Map(['first', 'second', 'third', 'fourth'].map(id => [id, deferred()]))
  t.mock.method(globalThis, 'fetch', async (url) => {
    const parsed = new URL(url)
    if (parsed.pathname.endsWith('/directories')) return pending.get(parsed.searchParams.get('directory_id')).promise
    if (parsed.pathname.endsWith('/jobs')) return response([])
    throw new Error(`Unexpected request ${parsed.pathname}`)
  })
  const view = await mount({ apiBase: 'http://api.test', datasetId: 'dataset-a' })
  try {
    await settle()
    const first = view.state.openBrowser('first')
    const second = view.state.openBrowser('second')
    pending.get('first').reject(new Error('old navigation failed'))
    await first
    assert.equal(view.state.browsing, true)
    assert.equal(view.state.directoryError, '')
    pending.get('second').resolve(response(directory('second')))
    await second
    assert.equal(view.state.browser.directory_id, 'second')
    assert.equal(view.state.browsing, false)

    const third = view.state.enterDirectory('third')
    const fourth = view.state.enterDirectory('fourth')
    pending.get('fourth').resolve(response(directory('fourth')))
    await fourth
    pending.get('third').resolve(response(directory('third')))
    await third
    assert.equal(view.state.browser.directory_id, 'fourth')
    assert.equal(view.state.browserOpen, true)
    assert.equal(view.state.directoryError, '')
  } finally { view.unmount() }
})

test('navigation invalidates pending preflight without clearing a newer check or replacing its preview', async (t) => {
  const checks = []
  t.mock.method(globalThis, 'fetch', async (url) => {
    const parsed = new URL(url)
    if (parsed.pathname.endsWith('/directories')) return response(directory(parsed.searchParams.get('directory_id')))
    if (parsed.pathname.endsWith('/preflight')) {
      const pending = deferred()
      checks.push({ ...pending, directoryId: parsed.searchParams.get('directory_id') })
      return pending.promise
    }
    if (parsed.pathname.endsWith('/jobs')) return response([])
    throw new Error(`Unexpected request ${parsed.pathname}`)
  })
  const view = await mount({ apiBase: 'http://api.test', datasetId: 'dataset-a' })
  try {
    await settle()
    await view.state.openBrowser('first')
    const first = view.state.checkDirectory()
    await view.state.enterDirectory('second')
    const second = view.state.checkDirectory()
    checks[0].resolve(response({ ...preview, directory_id: 'first' }))
    await first
    assert.equal(view.state.preflight, null)
    assert.equal(view.state.preflighting, true)
    view.state.chooseDirectory()
    assert.equal(view.state.selectedDirectory, null)
    checks[1].resolve(response({ ...preview, directory_id: 'second' }))
    await second
    assert.equal(view.state.preflight.directory_id, 'second')

    await view.state.enterDirectory('third')
    const third = view.state.checkDirectory()
    await view.state.enterDirectory('fourth')
    const fourth = view.state.checkDirectory()
    checks[3].resolve(response({ ...preview, directory_id: 'fourth', html_count: 4 }))
    await fourth
    checks[2].resolve(response({ ...preview, directory_id: 'third', html_count: 3 }))
    await third
    assert.equal(view.state.preflight.directory_id, 'fourth')
    assert.equal(view.state.preflight.html_count, 4)
    view.state.chooseDirectory()
    assert.equal(view.state.selectedDirectory.directoryId, 'fourth')
    assert.equal(view.state.selectedPreflight.directory_id, 'fourth')
  } finally { view.unmount() }
})

test('a preview for a different directory cannot confirm a selection or create a task', async (t) => {
  const creates = []
  t.mock.method(globalThis, 'fetch', async (url, options = {}) => {
    const parsed = new URL(url)
    if (parsed.pathname.endsWith('/directories')) return response(directory('current'))
    if (parsed.pathname.endsWith('/preflight')) return response({ ...preview, directory_id: 'other' })
    if (options.method === 'POST') creates.push(options)
    return response([])
  })
  const view = await mount({ apiBase: 'http://api.test', datasetId: 'dataset-a' })
  try {
    await settle()
    await view.state.openBrowser('current')
    await view.state.checkDirectory()
    assert.equal(view.state.preflight, null)
    assert.match(view.state.directoryError, /预检目录与当前目录不一致/)
    view.state.chooseDirectory()
    await view.state.create()
    assert.equal(view.state.selectedDirectory, null)
    assert.deepEqual(creates, [])
  } finally { view.unmount() }
})

test('dataset changes during directory JSON parsing discard old errors without ending a new navigation', async (t) => {
  const oldJson = deferred()
  const newJson = deferred()
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    const parsed = new URL(url)
    if (parsed.pathname.endsWith('/directories')) {
      const pending = options.headers.get('X-Dataset-ID') === 'dataset-a' ? oldJson : newJson
      return { ...response({}), json: () => pending.promise }
    }
    if (parsed.pathname.endsWith('/jobs')) return response([])
    throw new Error(`Unexpected request ${parsed.pathname}`)
  })
  const view = await mount({ apiBase: 'http://api.test', datasetId: 'dataset-a' })
  try {
    await settle()
    const oldRequest = view.state.openBrowser('old')
    await settle()
    view.props.datasetId = 'dataset-b'
    await settle()
    assert.equal(view.state.browser, null)
    const newRequest = view.state.openBrowser('new')
    await settle()
    oldJson.resolve(directory('old'))
    await oldRequest
    assert.equal(view.state.directoryError, '')
    assert.equal(view.state.browser, null)
    assert.equal(view.state.browsing, true)
    newJson.resolve(directory('new'))
    await newRequest
    assert.equal(view.state.browser.directory_id, 'new')
    assert.equal(view.state.browsing, false)
  } finally { view.unmount() }
})

test('dataset changes clear confirmed selections and invalidate pending preflight JSON', async (t) => {
  const oldJson = deferred()
  const newJson = deferred()
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    const parsed = new URL(url)
    if (parsed.pathname.endsWith('/directories')) return response(directory('batch'))
    if (parsed.pathname.endsWith('/preflight')) {
      const datasetId = options.headers.get('X-Dataset-ID')
      if (datasetId === 'dataset-a') return response(preview)
      return { ...response({}), json: () => (datasetId === 'dataset-b' ? oldJson : newJson).promise }
    }
    if (parsed.pathname.endsWith('/jobs')) return response([])
    throw new Error(`Unexpected request ${parsed.pathname}`)
  })
  const view = await mount({ apiBase: 'http://api.test', datasetId: 'dataset-a' })
  try {
    await settle()
    await view.state.openBrowser('batch')
    await view.state.checkDirectory()
    view.state.chooseDirectory()
    assert.equal(view.state.selectedDirectory.directoryId, 'batch')
    view.props.datasetId = 'dataset-b'
    await settle()
    assert.equal(view.state.selectedDirectory, null)
    assert.equal(view.state.selectedPreflight, null)
    await view.state.openBrowser('batch')
    const oldRequest = view.state.checkDirectory()
    await settle()
    view.props.datasetId = 'dataset-c'
    await settle()
    assert.equal(view.state.browser, null)
    assert.equal(view.state.preflight, null)
    await view.state.openBrowser('batch')
    const newRequest = view.state.checkDirectory()
    await settle()
    oldJson.resolve(preview)
    await oldRequest
    assert.equal(view.state.directoryError, '')
    assert.equal(view.state.preflight, null)
    assert.equal(view.state.preflighting, true)
    newJson.resolve(preview)
    await newRequest
    view.state.chooseDirectory()
    assert.equal(view.state.selectedDirectory.directoryId, 'batch')
    assert.equal(view.state.selectedPreflight.directory_id, 'batch')
  } finally { view.unmount() }
})

test('closing the browser invalidates pending navigation and preflight', async (t) => {
  const pendingNavigation = deferred()
  const pendingPreflight = deferred()
  t.mock.method(globalThis, 'fetch', async (url) => {
    const parsed = new URL(url)
    if (parsed.pathname.endsWith('/directories')) {
      if (parsed.searchParams.get('directory_id') === 'pending') return pendingNavigation.promise
      return response(directory('batch'))
    }
    if (parsed.pathname.endsWith('/preflight')) return pendingPreflight.promise
    if (parsed.pathname.endsWith('/jobs')) return response([])
    throw new Error(`Unexpected request ${parsed.pathname}`)
  })
  const view = await mount({ apiBase: 'http://api.test', datasetId: 'dataset-a' })
  try {
    await settle()
    await view.state.openBrowser('batch')
    const check = view.state.checkDirectory()
    view.state.closeBrowser()
    pendingPreflight.resolve(response(preview))
    await check
    assert.equal(view.state.preflight, null)
    assert.equal(view.state.browserOpen, false)
    const navigation = view.state.openBrowser('pending')
    view.state.closeBrowser()
    pendingNavigation.resolve(response(directory('pending')))
    await navigation
    assert.equal(view.state.browserOpen, false)
    assert.equal(view.state.browsing, false)
    assert.equal(view.state.preflighting, false)
  } finally { view.unmount() }
})

test('an old task creation cannot clear new dataset loading and keeps the selected mode and OCR', async (t) => {
  const oldJson = deferred()
  const newJson = deferred()
  const creates = []
  t.mock.method(globalThis, 'fetch', async (url, options = {}) => {
    const parsed = new URL(url)
    if (parsed.pathname.endsWith('/directories')) return response(directory('batch'))
    if (parsed.pathname.endsWith('/preflight')) return response(preview)
    if (options.method === 'POST') {
      creates.push(options)
      const pending = options.headers.get('X-Dataset-ID') === 'dataset-a' ? oldJson : newJson
      return { ...response({}, 202), json: () => pending.promise }
    }
    return response([])
  })
  const view = await mount({ apiBase: 'http://api.test', datasetId: 'dataset-a' })
  const select = async () => {
    await view.state.openBrowser('batch')
    await view.state.checkDirectory()
    view.state.chooseDirectory()
  }
  try {
    await settle()
    await select()
    view.state.mode = 'rules'
    view.state.ocr = false
    const oldCreate = view.state.create()
    await settle()
    await view.state.create()
    assert.equal(creates.length, 1, 'a pending confirmation cannot create a duplicate task')
    view.props.datasetId = 'dataset-b'
    await settle()
    await select()
    const newCreate = view.state.create()
    await settle()
    oldJson.resolve({ id: 'old-job' })
    await oldCreate
    assert.equal(view.state.busy, true)
    assert.equal(view.state.error, '')
    newJson.resolve({ id: 'new-job' })
    await newCreate
    assert.equal(view.state.busy, false)
    assert.deepEqual(creates.map(options => options.headers.get('X-Dataset-ID')), ['dataset-a', 'dataset-b'])
    for (const options of creates) {
      assert.deepEqual(JSON.parse(options.body), {
        directory_id: 'batch', preflight_fingerprint: 'fingerprint-001', mode: 'rules', ocr: false,
      })
    }
  } finally { view.unmount() }
})

test('pause, resume, and failed retry keep their POST routes and dataset headers', async (t) => {
  const actions = []
  const requests = []
  t.mock.method(globalThis, 'fetch', async (url, options = {}) => {
    requests.push({ url: new URL(url), options })
    if (options.method === 'POST') actions.push({ url: new URL(url), options })
    return response(options.method === 'POST' ? { message: 'ok' } : [])
  })
  const view = await mount({ apiBase: 'http://api.test', datasetId: 'dataset-a' })
  try {
    await settle()
    for (const operation of ['pause', 'resume', 'resume?retry_failed=true']) {
      await view.state.action({ id: 'job-one' }, operation)
    }
    assert.deepEqual(actions.map(({ url }) => url.pathname + url.search), [
      '/api/v1/jobs/job-one/pause',
      '/api/v1/jobs/job-one/resume',
      '/api/v1/jobs/job-one/resume?retry_failed=true',
    ])
    assert.ok(actions.every(({ options }) => options.headers.get('X-Dataset-ID') === 'dataset-a'))
    assert.ok(requests.every(({ options }) => options.credentials === 'include'),
      'job controls and the list refreshes after them include session cookies')
  } finally { view.unmount() }
})

test('downloading a job report includes session cookies on its cross-origin GET', async (t) => {
  const requests = []
  t.mock.method(globalThis, 'fetch', async (url, options = {}) => {
    requests.push({ url: new URL(url), options })
    return response({ job_id: 'job-one' })
  })
  const originalDocument = Object.getOwnPropertyDescriptor(globalThis, 'document')
  globalThis.document = { createElement: () => ({ click() {} }) }
  const view = await mount({ apiBase: 'http://api.test', datasetId: 'dataset-a' })
  try {
    await settle()
    requests.length = 0
    await view.state.report({ id: 'job-one' })

    assert.equal(requests.length, 1)
    assert.equal(requests[0].url.pathname, '/api/v1/jobs/job-one/report')
    assert.equal(requests[0].options.credentials, 'include')
    assert.equal(requests[0].options.headers.get('X-Dataset-ID'), 'dataset-a')
  } finally {
    view.unmount()
    if (originalDocument) Object.defineProperty(globalThis, 'document', originalDocument)
    else delete globalThis.document
  }
})
