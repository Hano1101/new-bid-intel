import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive, ref } from 'vue'

// Compile and execute the actual component templates/actions with a small host
// renderer. These tests verify component behavior, not browser visual layout.
const moduleUrls = new Map()
async function componentUrl(name) {
  if (moduleUrls.has(name)) return moduleUrls.get(name)
  const sourceUrl = new URL(`../src/components/${name}`, import.meta.url)
  const { descriptor } = parse(await readFile(sourceUrl, 'utf8'))
  const script = compileScript(descriptor, { id: name })
  const template = compileTemplate({ source: descriptor.template.content, filename: sourceUrl.pathname, id: name,
    compilerOptions: { bindingMetadata: script.bindings, hoistStatic: false } })
  assert.deepEqual(template.errors, [])
  let code = `${script.content.replace('export default', 'const component =')}\n${template.code.replace('export function render', 'function render')}\ncomponent.render = render; export default component`
  const imports = [...code.matchAll(/from (['"])([^'"]+)\1/g)]
  for (const match of imports) {
    const specifier = match[2]
    const resolved = specifier.endsWith('.vue') ? await componentUrl(specifier.split('/').at(-1))
      : specifier.startsWith('.') ? new URL(specifier, sourceUrl).href : import.meta.resolve(specifier)
    code = code.replace(match[0], `from ${match[1]}${resolved}${match[1]}`)
  }
  const url = `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
  moduleUrls.set(name, url)
  return url
}
function makeRenderer() {
  const remove = node => {
    if (!node.parent) return
    const index = node.parent.children.indexOf(node)
    if (index >= 0) node.parent.children.splice(index, 1)
    node.parent = null
  }
  const node = (tag, text = null) => ({
    tag, props: {}, children: [], parent: null, text, listeners: {},
    tagName: tag.toUpperCase(), addEventListener(event, action) { this.listeners[event] = action },
    get options() { return this.children.filter(child => child.tag === 'option') },
    get value() { return this.props.value }, set value(value) { this.props.value = value },
  })
  return createRenderer({
    createElement: tag => node(tag), createText: text => node('#text', text), createComment: text => node('#comment', text),
    setText: (element, text) => { element.text = text },
    setElementText: (element, text) => { element.children = []; element.text = text },
    insert(element, parent, anchor = null) {
      remove(element)
      const index = anchor ? parent.children.indexOf(anchor) : -1
      if (index < 0) parent.children.push(element)
      else parent.children.splice(index, 0, element)
      element.parent = parent
      parent.text = null
    },
    remove, patchProp: (element, key, previous, value) => { element.props[key] = value },
    parentNode: element => element.parent,
    nextSibling: element => element.parent?.children[element.parent.children.indexOf(element) + 1] || null,
  })
}
async function settle() {
  for (let index = 0; index < 18; index += 1) { await Promise.resolve(); await nextTick() }
}
async function mount(name, values) {
  const component = (await import(await componentUrl(name))).default
  const props = reactive(values)
  const instance = ref(null)
  const root = { children: [], parent: null, text: null }
  const emitted = []
  const app = makeRenderer().createApp({ render: () => h(component, { ...props, ref: instance, onOpenEvidence: value => emitted.push(value) }) })
  app.mount(root)
  await settle()
  return { props, root, state: instance.value.$.setupState, emitted, unmount: () => app.unmount() }
}
const response = (payload, status = 200) => ({ ok: status >= 200 && status < 300, status, headers: new Headers(), json: async () => payload })
function deferred() {
  let resolve
  const promise = new Promise(yes => { resolve = yes })
  return { promise, resolve }
}
function walk(root, predicate, found = []) {
  if (predicate(root)) found.push(root)
  for (const child of root.children || []) walk(child, predicate, found)
  return found
}
const byClass = (root, name) => walk(root, row => String(row.props?.class || '').split(/\s+/).includes(name))
const textContent = root => root.text != null ? String(root.text) : (root.children || []).map(textContent).join('')
const version = (id, noticeId = 10, latest = false) => ({ version_id: id, notice_id: noticeId, is_latest: latest,
  imported_at: '2026-10-11T02:00:00Z', reason: '合成快照', identity_status: 'matched', source_files: [{ source_file: `${id}.html` }] })
const history = (versions = [version('old', 9), version('new', 10, true)], identityStatus = 'matched') => ({ notice_id: 10,
  group_id: 'group-a', versions, latest_version_id: versions.find(row => row.is_latest)?.version_id || null, identity_status: identityStatus })
const details = id => ({ version_id: id, snapshot: { metadata: { project_name: `项目 ${id}`, project_number: 'TEST-001', project_budget: '100.00' },
  source_files: [{ source_file: `${id}.html`, sha256: 'a'.repeat(64), byte_size: 321 }] } })
const comparison = {
  changes: [
    { entity_type: 'item', entity_key: 'item:91', field: 'unit_price', change_type: 'changed', classification: 'possible_semantic',
      before: '10', after: '12', requires_manual_confirmation: true,
      before_source: { notice_id: 9, candidate_id: 91, source_file: 'old.pdf', source_location: 'page:1', source_evidence: '设备 10' },
      after_source: { notice_id: 10, candidate_id: 92, source_file: 'new.pdf', source_location: 'page:2', source_evidence: '设备 12' } },
    { entity_type: 'body', entity_key: 'body', field: 'content', change_type: 'changed', classification: 'format_only', before: '<p> A </p>', after: '<p>A</p>' },
    { entity_type: 'package', entity_key: 'pkg-B', field: 'package_code', change_type: 'added', classification: 'possible_semantic', before: null, after: 'B' },
  ], summary: { total: 3, semantic: 2, format_only: 1, provenance_only: 0, requires_manual_confirmation: 1 },
}
function fetchVersions(requests, result = history()) {
  return async (url, options) => {
    const parsed = new URL(url)
    requests.push({ url: parsed, options })
    if (parsed.pathname.endsWith('/compare')) return response(comparison)
    if (parsed.pathname.includes('/versions/')) return response(details(parsed.pathname.split('/').at(-1)))
    return response(result)
  }
}

test('version list selects latest, opens an old detail and compares the selected pair with dataset headers', async () => {
  const requests = []
  const view = await mount('NoticeVersionHistory.vue', { noticeId: 10, datasetId: 'dataset-a', apiBase: 'http://api.test', fetchImpl: fetchVersions(requests) })
  try {
    assert.equal(view.state.currentVersionId, 'new')
    assert.equal(view.state.beforeVersionId, 'old')
    assert.equal(view.state.afterVersionId, 'new')
    assert.match(textContent(view.root), /当前版本/)
    assert.match(textContent(view.root), /历史版本/)
    assert.match(textContent(view.root), /项目 new/)
    assert.match(textContent(view.root), /321 字节/)
    const oldRow = byClass(view.root, 'notice-versions__row')[0]
    oldRow.props.onClick()
    await settle()
    assert.equal(view.state.currentVersionId, 'old')
    assert.match(textContent(view.root), /项目 old/)
    await view.state.compareVersions()
    await settle()
    assert.match(textContent(view.root), /仅格式变化/)
    assert.match(textContent(view.root), /可能语义变化/)
    const compared = requests.find(request => request.url.pathname.endsWith('/compare'))
    assert.equal(compared.url.searchParams.get('before_version_id'), 'old')
    assert.equal(compared.url.searchParams.get('after_version_id'), 'new')
    assert.ok(requests.every(request => request.options.headers.get('X-Dataset-ID') === 'dataset-a'))
    const evidence = byClass(view.root, 'version-diff__evidence')
    evidence[0].props.onClick()
    evidence[1].props.onClick()
    assert.deepEqual(view.emitted.map(row => [row.notice_id, row.item_id, row.version_id]), [[9, 91, 'old'], [10, 92, 'new']])
  } finally { view.unmount() }
})

test('changing the comparison pair clears the previous diff and the same version cannot be compared', async () => {
  const requests = []
  const view = await mount('NoticeVersionHistory.vue', { noticeId: 10, datasetId: 'a', apiBase: 'http://api.test', fetchImpl: fetchVersions(requests) })
  try {
    await view.state.compareVersions()
    assert.ok(view.state.comparison)
    view.state.beforeVersionId = 'new'
    await settle()
    assert.equal(view.state.comparison, null)
    assert.equal(view.state.canCompare, false)
    assert.match(textContent(view.root), /请选择两个不同版本/)
    const count = requests.length
    await view.state.compareVersions()
    assert.equal(requests.length, count)
  } finally { view.unmount() }
})

test('empty historical data, a single snapshot and uncertain identity have explicit states', async () => {
  for (const [payload, pattern] of [
    [history([]), /历史数据不会自动补造版本/],
    [history([version('only', 10, true)]), /当前只有一个版本/],
    [history([version('pending', 10, true)], 'manual_link_required'), /身份待确认.*人工确认关联/],
  ]) {
    const view = await mount('NoticeVersionHistory.vue', { noticeId: 10, datasetId: 'a', apiBase: 'http://api.test', fetchImpl: fetchVersions([], payload) })
    try { assert.match(textContent(view.root), pattern); assert.equal(view.state.canCompare, false) }
    finally { view.unmount() }
  }
})

test('an API failure is visible and refresh can recover the version list', async () => {
  let fail = true
  const normal = fetchVersions([])
  const view = await mount('NoticeVersionHistory.vue', { noticeId: 10, datasetId: 'a', apiBase: 'http://api.test',
    fetchImpl: (...args) => fail ? response({ detail: '版本暂不可读取' }, 503) : normal(...args) })
  try {
    assert.match(textContent(view.root), /版本暂不可读取/)
    assert.equal(view.state.busy, false)
    fail = false
    await view.state.refresh()
    assert.equal(view.state.error, '')
    assert.equal(view.state.versions.length, 2)
  } finally { view.unmount() }
})

test('late history JSON from A to B to A cannot populate the active dataset or stop its loading', async () => {
  const oldJson = deferred()
  const newRequest = deferred()
  let count = 0
  const requested = []
  const view = await mount('NoticeVersionHistory.vue', { noticeId: 10, datasetId: 'a', apiBase: 'http://api.test', fetchImpl: async (url, options) => {
    requested.push(options.headers.get('X-Dataset-ID'))
    if (new URL(url).pathname.includes('/versions/')) return response(details('b'))
    count += 1
    if (count === 1) return { ...response({}), json: () => oldJson.promise }
    if (count === 3) return newRequest.promise
    return response(history([version('b', 20, true)]))
  } })
  try {
    view.props.datasetId = 'b'
    await settle()
    assert.equal(view.state.currentVersionId, 'b')
    view.props.datasetId = 'a'
    await settle()
    oldJson.resolve(history([version('stale', 99, true)]))
    await settle()
    assert.equal(view.state.versions.length, 0)
    assert.equal(view.state.busy, true)
    newRequest.resolve(response(history([version('active', 10, true)])))
    await settle()
    assert.equal(view.state.currentVersionId, 'active')
    assert.equal(view.state.error, '')
    assert.ok(requested.includes('b'))
  } finally { view.unmount() }
})

test('late detail and comparison requests do not replace newer version selections', async () => {
  const pendingDetail = deferred()
  const pendingComparison = deferred()
  const normal = fetchVersions([])
  let delayed = false
  const view = await mount('NoticeVersionHistory.vue', { noticeId: 10, datasetId: 'a', apiBase: 'http://api.test', fetchImpl: async (...args) => {
    const url = new URL(args[0])
    if (delayed && url.pathname.endsWith('/versions/old')) return pendingDetail.promise
    if (url.pathname.endsWith('/compare')) return pendingComparison.promise
    return normal(...args)
  } })
  try {
    delayed = true
    const detailTask = view.state.selectVersion('old')
    await view.state.selectVersion('new')
    pendingDetail.resolve(response(details('old')))
    await detailTask
    assert.equal(view.state.detail.version_id, 'new')
    const comparisonTask = view.state.compareVersions()
    view.state.beforeVersionId = 'new'
    pendingComparison.resolve(response(comparison))
    await comparisonTask
    assert.equal(view.state.comparison, null)
    assert.equal(view.state.comparing, false)
  } finally { view.unmount() }
})

test('difference filters operate on the rendered changes and retain added, changed and manual statuses', async () => {
  const view = await mount('NoticeVersionDiff.vue', { comparison, noticeId: 10, beforeVersionId: 'old', afterVersionId: 'new' })
  try {
    assert.equal(byClass(view.root, 'version-diff__change').length, 3)
    const typeSelector = walk(view.root, row => row.props?.['aria-label'] === '差异类型')[0]
    typeSelector.props['onUpdate:modelValue']('item')
    await nextTick()
    assert.equal(byClass(view.root, 'version-diff__change').length, 1)
    assert.match(textContent(view.root), /单价/)
    view.state.changeFilter = 'removed'
    await nextTick()
    assert.match(textContent(view.root), /当前筛选下没有差异/)
    view.state.entityFilter = ''
    view.state.changeFilter = ''
    view.state.classificationFilter = 'format_only'
    await nextTick()
    assert.equal(byClass(view.root, 'version-diff__change').length, 1)
    assert.match(textContent(byClass(view.root, 'version-diff__change')[0]), /正文/)
    view.state.classificationFilter = ''
    view.state.manualOnly = true
    await nextTick()
    assert.equal(byClass(view.root, 'version-diff__change').length, 1)
    assert.match(textContent(byClass(view.root, 'version-diff__change')[0]), /待人工确认/)
    view.props.comparison = { changes: [], summary: { total: 0 } }
    await nextTick()
    assert.equal(view.state.manualOnly, false)
    assert.match(textContent(view.root), /两个版本没有保存的字段差异/)
  } finally { view.unmount() }
})

test('the main evidence entry preserves the version target and loads the frozen evidence endpoint', async () => {
  const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const script = compileScript(descriptor, { id: 'notice-version-app-test' })
  const template = compileTemplate({ source: descriptor.template.content, filename: 'App.vue', id: 'notice-version-app-test',
    compilerOptions: { bindingMetadata: script.bindings } })
  assert.deepEqual(template.errors, [])
  assert.match(source, /versionId \? versionEvidencePath\(versionId\)/)
  assert.match(source, /await datasetFetch\(`\$\{apiBase\}\$\{path\}`\)/)
  assert.match(source, /#version-history/)
  assert.match(source, /@open-evidence="openNoticeDetail\(\$event\.notice_id, \$event\.item_id \|\| null, \$event\.version_id\)"/)
  const dialog = await readFile(new URL('../src/components/NoticeEvidenceDialog.vue', import.meta.url), 'utf8')
  assert.match(dialog, /<slot name="version-history" \/>/)
})
