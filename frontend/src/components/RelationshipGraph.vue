<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { createDatasetClient } from '../utils/datasets.js'

const props = defineProps({
  apiBase: { type: String, required: true },
  datasetId: { type: String, default: 'default' },
  limit: { type: Number, default: 100 },
  refreshKey: { type: [String, Number], default: 0 },
  fetchImpl: { type: Function, default: null },
})

const chartElement = ref(null)
const loading = ref(false)
const searching = ref(false)
const error = ref('')
const searchError = ref('')
const graph = ref(null)
const searchText = ref('')
const searchType = ref('all')
const searchResults = ref([])
const searchCount = ref(0)
const searchTotal = ref(0)
const searchTruncated = ref(false)
const searchHasMore = ref(false)
const searchOffset = ref(0)
const searched = ref(false)
const selectedEntity = ref(null)
const relationType = ref('')
let chart = null
let version = 0
let graphRequest = 0
let searchRequest = 0
let activeSearch = null
const datasetFetch = createDatasetClient(
  () => props.datasetId,
  () => version,
  (url, options = {}) => (props.fetchImpl || fetch)(url, { ...options, credentials: 'include' }),
)

const colors = ['#166534', '#155e75', '#9a3412', '#6b21a8']
const relationOptions = [
  ['PURCHASES', '采购单位采购'],
  ['HAS_PACKAGE', '项目包含采购包'],
  ['BID_IN', '供应商参与投标'],
  ['AWARDED_TO', '采购包授予供应商'],
  ['HAS_ITEM', '采购包包含标的'],
]
const entityTypeLabel = (result) => {
  if (result.entity_type === 'project') return '项目'
  const roles = result.roles || []
  if (roles.includes('buyer') && roles.includes('supplier')) return '采购单位 / 供应商'
  if (roles.includes('buyer')) return '采购单位'
  return '供应商'
}

function render() {
  if (!chart || !graph.value) return
  const payload = graph.value
  const categories = (payload.categories || []).map((name) => ({ name }))
  const categoryIndex = Object.fromEntries(categories.map((item, index) => [item.name, index]))
  chart.setOption({
    animationDuration: 350,
    tooltip: { formatter: (params) => params.dataType === 'edge' ? params.data.relation : params.data.name },
    legend: [{ data: categories.map((item) => item.name), top: 8, left: 'center' }],
    series: [{
      type: 'graph', layout: 'force', roam: true, draggable: true,
      data: (payload.nodes || []).map((node) => ({
        id: node.id, name: node.name, category: categoryIndex[node.category] ?? 0,
        value: node.properties, symbolSize: node.category === 'project' ? 34 : 22,
      })),
      links: (payload.links || []).map((link) => ({
        source: link.source, target: link.target, relation: link.relation,
        lineStyle: { opacity: 0.55, curveness: 0.08 },
      })),
      categories,
      label: { show: true, fontSize: 11, formatter: '{b}' },
      edgeLabel: { show: false },
      lineStyle: { color: 'source' },
      itemStyle: { borderColor: '#fff', borderWidth: 1 },
      emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
      force: { repulsion: 180, edgeLength: [80, 180], gravity: 0.08 },
    }],
    color: colors,
  })
}

async function load() {
  const current = ++graphRequest
  const datasetVersion = version
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams()
    if (selectedEntity.value) {
      params.set('entity_type', selectedEntity.value.entity_type)
      params.set('entity_id', String(selectedEntity.value.entity_id))
      params.set('hop', '1')
    } else {
      params.set('limit', String(Math.max(1, props.limit)))
    }
    if (relationType.value) params.set('relation_type', relationType.value)
    const response = await datasetFetch(`${props.apiBase}/api/v1/graph?${params}`)
    const result = await response.json()
    if (!response.ok) throw new Error(result.detail || '关系图读取失败')
    if (current !== graphRequest || datasetVersion !== version) return
    graph.value = result
    await nextTick()
    render()
  } catch (cause) {
    if (cause.name === 'AbortError' || current !== graphRequest) return
    error.value = cause.message || '关系图读取失败'
  } finally {
    if (current === graphRequest) loading.value = false
  }
}

async function runSearch(query, type, append = false) {
  if (!query) {
    searchRequest += 1
    searching.value = false
    searchResults.value = []
    searchCount.value = 0
    searchTotal.value = 0
    searchTruncated.value = false
    searchHasMore.value = false
    searchOffset.value = 0
    activeSearch = null
    searched.value = false
    searchError.value = ''
    return
  }
  if (!append) {
    activeSearch = { query, type }
    searchResults.value = []
    searchCount.value = 0
    searchTotal.value = 0
    searchTruncated.value = false
    searchHasMore.value = false
    searchOffset.value = 0
    searched.value = false
  }
  const current = ++searchRequest
  const datasetVersion = version
  const offset = append ? searchOffset.value : 0
  const params = new URLSearchParams({
    query, type, search_limit: '20', search_offset: String(offset),
  })
  searching.value = true
  searchError.value = ''
  try {
    const response = await datasetFetch(`${props.apiBase}/api/v1/graph?${params}`)
    const result = await response.json()
    if (!response.ok) throw new Error(result.detail || '主体搜索失败')
    if (current !== searchRequest || datasetVersion !== version) return
    const pageResults = result.results || []
    searchResults.value = append ? [...searchResults.value, ...pageResults] : pageResults
    searchCount.value = searchResults.value.length
    searchTotal.value = result.total_result_count || 0
    searchTruncated.value = Boolean(result.truncated)
    searchHasMore.value = Boolean(result.has_more ?? result.truncated)
    searchOffset.value = result.next_offset ?? offset + pageResults.length
    searched.value = true
  } catch (cause) {
    if (cause.name === 'AbortError' || current !== searchRequest) return
    searchError.value = cause.message || '主体搜索失败'
  } finally {
    if (current === searchRequest) searching.value = false
  }
}

function search() {
  return runSearch(searchText.value.trim(), searchType.value)
}

function loadMoreSearchResults() {
  if (!searchHasMore.value || searching.value || !activeSearch) return
  return runSearch(activeSearch.query, activeSearch.type, true)
}

function selectEntity(result) {
  selectedEntity.value = result
  return load()
}

function clearSelection() {
  selectedEntity.value = null
  relationType.value = ''
  return load()
}

function changeRelationType() {
  return load()
}

function resize() { chart?.resize() }

onMounted(() => {
  chart = echarts.init(chartElement.value)
  if (typeof window !== 'undefined') window.addEventListener('resize', resize)
  load()
})
watch(() => [props.datasetId, props.refreshKey], () => {
  version += 1
  graphRequest += 1
  searchRequest += 1
  graph.value = null
  selectedEntity.value = null
  searchResults.value = []
  searching.value = false
  searchCount.value = 0
  searchTotal.value = 0
  searchTruncated.value = false
  searchHasMore.value = false
  searchOffset.value = 0
  activeSearch = null
  searched.value = false
  searchError.value = ''
  chart?.clear()
  load()
}, { flush: 'sync' })
onBeforeUnmount(() => {
  version += 1
  graphRequest += 1
  searchRequest += 1
  if (typeof window !== 'undefined') window.removeEventListener('resize', resize)
  chart?.dispose()
})
</script>

<template>
  <section class="relationship-graph" aria-label="主体关系图">
    <div class="graph-heading">
      <div>
        <strong>主体关系图</strong>
        <small v-if="graph">SQLite 图谱 · {{ graph.project_count }} / {{ graph.total_project_count }} 个项目</small>
      </div>
      <button type="button" class="secondary" :disabled="loading" @click="load">{{ loading ? '读取中…' : '刷新' }}</button>
    </div>
    <form class="graph-search" @submit.prevent="search">
      <label>
        名称
        <input v-model="searchText" type="search" maxlength="100" placeholder="搜索主体或项目名称" />
      </label>
      <label>
        类型
        <select v-model="searchType">
          <option value="all">全部主体和项目</option>
          <option value="buyer">采购单位</option>
          <option value="supplier">供应商</option>
          <option value="project">项目</option>
        </select>
      </label>
      <button type="submit" :disabled="searching || !searchText.trim()">{{ searching ? '搜索中…' : '搜索全量数据' }}</button>
    </form>
    <p v-if="searchError" class="error graph-status">{{ searchError }}</p>
    <div v-if="searched" class="search-results" aria-live="polite">
      <p class="graph-status">匹配 {{ searchTotal }} 条，返回 {{ searchCount }} 条</p>
      <p v-if="searchTruncated" class="graph-status graph-truncated">搜索结果较多，可继续加载后续结果。</p>
      <p v-if="!searchCount" class="graph-status">没有匹配的主体或项目。</p>
      <ul v-if="searchCount">
        <li v-for="result in searchResults" :key="result.id">
          <button type="button" class="result-button" @click="selectEntity(result)">
            <span>{{ result.name }}</span>
            <small>{{ entityTypeLabel(result) }} · {{ result.id }}<template v-if="result.context"> · {{ result.context }}</template></small>
          </button>
        </li>
      </ul>
      <button v-if="searchHasMore" type="button" class="result-button graph-load-more" :disabled="searching" @click="loadMoreSearchResults">
        {{ searching ? '正在加载…' : '加载更多结果' }}
      </button>
    </div>
    <div class="graph-controls">
      <label>
        关系筛选
        <select v-model="relationType" @change="changeRelationType">
          <option value="">全部关系类型</option>
          <option v-for="[value, label] in relationOptions" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
      <button v-if="selectedEntity" type="button" class="secondary" :disabled="loading" @click="clearSelection">返回最近项目预览</button>
      <span v-if="selectedEntity" class="selection-label">当前：{{ selectedEntity.name }} · {{ entityTypeLabel(selectedEntity) }} · 1-hop</span>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="graph" class="graph-status" aria-live="polite">已返回 {{ graph.node_count }} 个节点、{{ graph.edge_count }} 条关系。</p>
    <p v-if="graph?.truncated" class="graph-status graph-truncated">{{ graph.truncation_hint || '关系子图已达到服务端显示上限。' }}</p>
    <div ref="chartElement" class="graph-canvas"></div>
    <p class="graph-note">搜索覆盖当前数据集的全部主体与项目；选中后读取服务端筛选的一跳关系。预览按最近项目生成。Neo4j 同步是可选后端，不影响此图。</p>
  </section>
</template>

<style scoped>
.relationship-graph { margin-top: 1.25rem; border: 1px solid #d9e2dc; border-radius: 18px; background: #fff; overflow: hidden; }
.graph-heading { display: flex; justify-content: space-between; align-items: center; padding: 1rem 1.2rem; border-bottom: 1px solid #edf1ee; }
.graph-heading strong, .graph-heading small { display: block; }
.graph-heading small { margin-top: .25rem; color: #708077; font-size: .78rem; }
.graph-search, .graph-controls { display: flex; align-items: end; flex-wrap: wrap; gap: .65rem; padding: .8rem 1.2rem; border-bottom: 1px solid #edf1ee; }
.graph-search label, .graph-controls label { display: grid; gap: .25rem; color: #52645a; font-size: .8rem; }
.graph-search input, .graph-search select, .graph-controls select { min-height: 2.3rem; border: 1px solid #cbd7cf; border-radius: 7px; padding: .35rem .55rem; background: white; color: #1f3327; }
.graph-search input { min-width: 15rem; }
.graph-search button, .result-button { border: 1px solid #166534; border-radius: 7px; padding: .48rem .7rem; background: #166534; color: #fff; cursor: pointer; }
.graph-search button:disabled { opacity: .55; cursor: not-allowed; }
.search-results { max-height: 13rem; overflow: auto; border-bottom: 1px solid #edf1ee; padding: .25rem 1.2rem .65rem; }
.search-results ul { display: grid; gap: .3rem; margin: .35rem 0 0; padding: 0; list-style: none; }
.result-button { display: flex; width: 100%; justify-content: space-between; gap: .75rem; text-align: left; background: #f5f8f5; color: #1f3327; border-color: #d9e2dc; }
.result-button small { color: #708077; text-align: right; }
.graph-status { margin: .55rem 1.2rem; color: #52645a; font-size: .82rem; }
.graph-truncated { color: #8a4b08; }
.selection-label { padding-bottom: .45rem; color: #52645a; font-size: .8rem; }
.graph-canvas { width: 100%; height: 430px; }
.graph-note { margin: 0; padding: .8rem 1.2rem 1rem; color: #708077; font-size: .78rem; }
</style>
