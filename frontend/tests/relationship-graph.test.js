import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive, ref } from 'vue'

const chartModule = `data:text/javascript;base64,${Buffer.from(
  'export function init() { return { setOption() {}, clear() {}, resize() {}, dispose() {} } }',
).toString('base64')}`

async function loadComponent() {
  const sourceUrl = new URL('../src/components/RelationshipGraph.vue', import.meta.url)
  const { descriptor } = parse(await readFile(sourceUrl, 'utf8'))
  const script = compileScript(descriptor, { id: 'RelationshipGraph' }).content.replace(
    /from (['"])([^'"]+)\1/g,
    (_, quote, specifier) => {
      if (specifier === 'echarts') return `from ${quote}${chartModule}${quote}`
      return `from ${quote}${specifier.startsWith('.') ? new URL(specifier, sourceUrl).href : import.meta.resolve(specifier)}${quote}`
    },
  )
  const component = (await import(`data:text/javascript;base64,${Buffer.from(script).toString('base64')}`)).default
  return { ...component, render: () => null }
}

const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  setText() {}, setElementText() {}, insert() {}, remove() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null,
})

async function mount(initialProps) {
  const component = await loadComponent()
  const props = reactive(initialProps)
  const instance = ref(null)
  const app = renderer.createApp({ render: () => h(component, { ...props, ref: instance }) })
  app.mount({})
  return { props, state: instance.value.$.setupState, unmount: () => app.unmount() }
}

const response = (payload) => ({ ok: true, status: 200, json: async () => payload })
const settle = async () => {
  await nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
}

test('search uses the selected dataset, and result selection/filtering request a bounded one-hop graph', async () => {
  const requests = []
  const buyer = { id: 'organization:42', entity_id: 42, entity_type: 'organization', name: '采购中心', roles: ['buyer'] }
  const fetchImpl = async (url, options) => {
    const parsed = new URL(url)
    requests.push({ url: parsed, options })
    if (parsed.searchParams.has('query')) {
      return response({ results: [buyer], result_count: 1, total_result_count: 1, truncated: false })
    }
    if (parsed.searchParams.has('entity_id')) {
      return response({ view: 'entity', nodes: [], links: [], categories: [], node_count: 1, edge_count: 0 })
    }
    return response({ view: 'preview', nodes: [], links: [], categories: [], node_count: 0, edge_count: 0 })
  }
  const view = await mount({ apiBase: 'http://api.test', datasetId: 'dataset-a', fetchImpl })
  try {
    await settle()
    view.state.searchText = '采购中心'
    view.state.searchType = 'buyer'
    await view.state.search()

    const searchRequest = requests.find(({ url }) => url.searchParams.has('query'))
    assert.equal(searchRequest.url.searchParams.get('query'), '采购中心')
    assert.equal(searchRequest.url.searchParams.get('type'), 'buyer')
    assert.equal(searchRequest.options.credentials, 'include')
    assert.equal(searchRequest.options.headers.get('X-Dataset-ID'), 'dataset-a')
    assert.equal(view.state.searchTotal, 1)
    assert.equal(view.state.searchResults[0].id, buyer.id)

    await view.state.selectEntity(buyer)
    const detailRequest = requests.find(({ url }) => url.searchParams.has('entity_id'))
    assert.equal(detailRequest.url.searchParams.get('entity_type'), 'organization')
    assert.equal(detailRequest.url.searchParams.get('entity_id'), '42')
    assert.equal(detailRequest.url.searchParams.get('hop'), '1')
    assert.equal(view.state.selectedEntity.id, buyer.id)

    view.state.relationType = 'BID_IN'
    await view.state.changeRelationType()
    const filtered = requests.at(-1)
    assert.equal(filtered.url.searchParams.get('relation_type'), 'BID_IN')
    assert.equal(filtered.url.searchParams.get('entity_id'), '42')

    await view.state.clearSelection()
    const preview = requests.at(-1)
    assert.equal(preview.url.searchParams.has('entity_id'), false)
    assert.equal(preview.url.searchParams.get('limit'), '100')
  } finally { view.unmount() }
})

test('empty and truncated result states are retained from the server response', async () => {
  let match = false
  const view = await mount({
    apiBase: 'http://api.test', datasetId: 'dataset-a',
    fetchImpl: async (url) => {
      if (new URL(url).searchParams.has('query')) {
        return response(match
          ? { results: [{ id: 'project:1', entity_id: 1, entity_type: 'project', name: '项目' }], result_count: 1, total_result_count: 25, truncated: true }
          : { results: [], result_count: 0, total_result_count: 0, truncated: false })
      }
      return response({ nodes: [], links: [], categories: [], node_count: 0, edge_count: 0 })
    },
  })
  try {
    await settle()
    view.state.searchText = '没有结果'
    await view.state.search()
    assert.equal(view.state.searched, true)
    assert.equal(view.state.searchCount, 0)
    assert.deepEqual(view.state.searchResults, [])

    match = true
    view.state.searchText = '项目'
    await view.state.search()
    assert.equal(view.state.searchTotal, 25)
    assert.equal(view.state.searchCount, 1)
    assert.equal(view.state.searchTruncated, true)
  } finally { view.unmount() }
})

test('search results load in stable bounded pages without changing the active query', async () => {
  const matches = Array.from({ length: 25 }, (_, index) => ({
    id: `organization:${index + 1}`,
    entity_id: index + 1,
    entity_type: 'organization',
    name: `供应商${String(index + 1).padStart(2, '0')}`,
    roles: ['supplier'],
  }))
  const requests = []
  const view = await mount({
    apiBase: 'http://api.test', datasetId: 'dataset-a',
    fetchImpl: async url => {
      const parsed = new URL(url)
      requests.push(parsed)
      if (!parsed.searchParams.has('query')) {
        return response({ nodes: [], links: [], categories: [], node_count: 0, edge_count: 0 })
      }
      const offset = Number(parsed.searchParams.get('search_offset'))
      const results = matches.slice(offset, offset + 20)
      const hasMore = offset + results.length < matches.length
      return response({
        results,
        result_count: results.length,
        total_result_count: matches.length,
        offset,
        next_offset: hasMore ? offset + results.length : null,
        has_more: hasMore,
        truncated: hasMore,
      })
    },
  })
  try {
    await settle()
    view.state.searchText = '供应商'
    view.state.searchType = 'supplier'
    await view.state.search()
    assert.equal(view.state.searchResults.length, 20)
    assert.equal(view.state.searchHasMore, true)
    assert.equal(view.state.searchOffset, 20)

    view.state.searchText = '未提交的新词'
    await view.state.loadMoreSearchResults()
    assert.equal(view.state.searchResults.length, 25)
    assert.equal(view.state.searchHasMore, false)
    assert.equal(view.state.searchOffset, 25)
    const queryRequests = requests.filter(request => request.searchParams.has('query'))
    assert.deepEqual(queryRequests.map(request => request.searchParams.get('search_offset')), ['0', '20'])
    assert.ok(queryRequests.every(request => request.searchParams.get('query') === '供应商'))
    assert.ok(queryRequests.every(request => request.searchParams.get('type') === 'supplier'))
  } finally { view.unmount() }
})
