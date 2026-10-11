import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, ref } from 'vue'

async function loadRelationshipClues() {
  const sourceUrl = new URL('../src/components/RelationshipClues.vue', import.meta.url)
  const { descriptor } = parse(await readFile(sourceUrl, 'utf8'))
  const script = compileScript(descriptor, { id: 'relationship-clues-test' })
  const template = compileTemplate({
    source: descriptor.template.content,
    filename: sourceUrl.pathname,
    id: 'relationship-clues-test',
    compilerOptions: { bindingMetadata: script.bindings, hoistStatic: false },
  })
  assert.deepEqual(template.errors, [])
  const resolveImports = code => code.replace(
    /from (['"])([^'"]+)\1/g,
    (_, quote, specifier) => `from ${quote}${specifier.startsWith('.') ? new URL(specifier, sourceUrl).href : import.meta.resolve(specifier)}${quote}`,
  )
  const scriptModule = await import(`data:text/javascript;base64,${Buffer.from(resolveImports(script.content)).toString('base64')}`)
  const templateModule = await import(`data:text/javascript;base64,${Buffer.from(resolveImports(template.code)).toString('base64')}`)
  return { ...scriptModule.default, render: templateModule.render }
}

function makeRenderer() {
  const remove = node => {
    if (!node.parent) return
    const index = node.parent.children.indexOf(node)
    if (index >= 0) node.parent.children.splice(index, 1)
    node.parent = null
  }
  return createRenderer({
    createElement: type => ({ type, props: {}, children: [], parent: null, text: null }),
    createText: text => ({ type: '#text', props: {}, children: [], parent: null, text }),
    createComment: text => ({ type: '#comment', props: {}, children: [], parent: null, text }),
    setText: (node, text) => { node.text = text },
    setElementText: (node, text) => { node.children = []; node.text = text },
    insert: (node, parent, anchor = null) => {
      remove(node)
      const index = anchor ? parent.children.indexOf(anchor) : -1
      if (index < 0) parent.children.push(node)
      else parent.children.splice(index, 0, node)
      node.parent = parent
      parent.text = null
    },
    remove,
    patchProp: (node, key, _previous, value) => { node.props[key] = value },
    parentNode: node => node.parent,
    nextSibling: node => {
      if (!node.parent) return null
      return node.parent.children[node.parent.children.indexOf(node) + 1] || null
    },
  })
}

function walk(node, predicate, found = []) {
  if (predicate(node)) found.push(node)
  for (const child of node.children || []) walk(child, predicate, found)
  return found
}

const byClass = (root, className) => walk(root, node => String(node.props?.class || '').split(/\s+/).includes(className))
const byId = (root, id) => walk(root, node => node.props?.id === id)[0]
const isHidden = (root, id) => Object.hasOwn(byId(root, id).props, 'hidden')
const textContent = node => node?.text != null ? String(node.text) : (node?.children || []).map(textContent).join('')
const click = async node => {
  assert.equal(node?.props?.type, 'button', 'native buttons remain keyboard operable')
  node.props.onClick()
  await nextTick()
}

const cluePayload = {
  definitions: { project_count: { label: '项目去重', description: '按 project_id 去重' } },
  clues: [
    {
      id: 'clue-1', type: 'common-bidding', title: '同包共投线索',
      summary: '这是需要展开后阅读的长摘要。',
      metrics: { project_count: 2, package_count: 3 },
      entities: ['供应商甲', '供应商乙'],
      evidence: {
        notices: [{ notice_id: 11, title: '公告甲' }],
        projects: [{ project_id: 21, project_name: '项目甲' }],
        packages: [{ package_code: 'A' }],
      },
      evidence_links: [{ notice_id: 11, label: '打开公告证据' }],
      warnings: [{ code: 'ocr_low_confidence', message: 'OCR 内容待核查' }],
    },
    {
      id: 'clue-2', type: 'repeat-cooperation', title: '重复合作线索',
      summary: '第二条线索摘要。', metrics: { project_count: 1, package_count: 1 },
      evidence: { notices: [], projects: [], packages: [] },
    },
  ],
}

async function mountRelationshipClues() {
  const component = await loadRelationshipClues()
  const renderer = makeRenderer()
  const root = { children: [], parent: null, text: null }
  const instance = ref(null)
  const emitted = []
  const app = renderer.createApp({
    render: () => h(component, {
      apiBase: 'http://api.test',
      fetchImpl: async () => ({ ok: true, json: async () => cluePayload }),
      onOpenNotice: payload => emitted.push(payload),
      ref: instance,
    }),
  })
  app.mount(root)
  await instance.value.$.setupState.load()
  await nextTick()
  return { root, emitted, state: instance.value.$.setupState, unmount: () => app.unmount() }
}

test('relationship clues start collapsed with titles, status and project/package counts visible', async () => {
  const view = await mountRelationshipClues()
  try {
    const cards = byClass(view.root, 'relationship-clue-card')
    assert.equal(cards.length, 2)
    for (const [index, card] of cards.entries()) {
      const toggle = byClass(card, 'clue-toggle')[0]
      assert.equal(toggle.props['aria-expanded'], false)
      assert.equal(toggle.props['aria-controls'], `relationship-clue-details-${index}`)
      assert.match(textContent(card), /待核查线索/)
      assert.match(textContent(card), /项目数/)
      assert.match(textContent(card), /采购包数/)
    }
    assert.match(textContent(cards[0]), /同包共投线索/)
    assert.match(textContent(byClass(cards[0], 'clue-metrics')[0]), /2项目数/)
    assert.match(textContent(byClass(cards[0], 'clue-metrics')[0]), /3采购包数/)
    assert.match(textContent(view.root), /统计口径与解释/)
    assert.equal(isHidden(view.root, 'relationship-clue-details-0'), true)
    assert.equal(isHidden(view.root, 'relationship-clue-details-1'), true)
    assert.equal(byClass(view.root, 'clue-toggle-all')[0].props['aria-expanded'], false)
  } finally { view.unmount() }
})

test('a clue can be expanded and collapsed independently', async () => {
  const view = await mountRelationshipClues()
  try {
    const firstToggle = byClass(view.root, 'clue-toggle')[0]
    await click(firstToggle)
    assert.equal(firstToggle.props['aria-expanded'], true)
    assert.equal(isHidden(view.root, 'relationship-clue-details-0'), false)
    assert.equal(isHidden(view.root, 'relationship-clue-details-1'), true)

    await click(firstToggle)
    assert.equal(firstToggle.props['aria-expanded'], false)
    assert.equal(isHidden(view.root, 'relationship-clue-details-0'), true)
  } finally { view.unmount() }
})

test('the all-clues control expands and collapses every clue', async () => {
  const view = await mountRelationshipClues()
  try {
    const toggleAll = byClass(view.root, 'clue-toggle-all')[0]
    await click(toggleAll)
    assert.equal(toggleAll.props['aria-expanded'], true)
    assert.equal(isHidden(view.root, 'relationship-clue-details-0'), false)
    assert.equal(isHidden(view.root, 'relationship-clue-details-1'), false)

    await click(toggleAll)
    assert.equal(toggleAll.props['aria-expanded'], false)
    assert.equal(isHidden(view.root, 'relationship-clue-details-0'), true)
    assert.equal(isHidden(view.root, 'relationship-clue-details-1'), true)
  } finally { view.unmount() }
})

test('expanded clues keep the notice evidence entry usable', async () => {
  const view = await mountRelationshipClues()
  try {
    await click(byClass(view.root, 'clue-toggle')[0])
    const firstCard = byClass(view.root, 'relationship-clue-card')[0]
    assert.match(textContent(firstCard), /OCR 内容待核查/)
    assert.match(textContent(firstCard), /公告甲/)
    assert.match(textContent(firstCard), /项目甲/)
    assert.match(textContent(firstCard), /构成采购包 1A/)
    const evidenceButton = walk(view.root, node => node.type === 'button' && textContent(node).includes('打开公告证据'))[0]
    assert.ok(evidenceButton)
    await click(evidenceButton)
    assert.equal(view.emitted.length, 1)
    assert.equal(view.emitted[0].noticeId, 11)
    assert.equal(view.emitted[0].clue.notice_id, 11)
  } finally { view.unmount() }
})
