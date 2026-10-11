import assert from 'node:assert/strict'
import test from 'node:test'
import {
  displayVersionValue, filterVersionChanges, versionEvidencePath, versionEvidenceTarget, versionIdentityLabel, versionLabel,
} from '../src/utils/versionDiff.js'

test('difference filters combine entity, change, nature and manual review without mutating results', () => {
  const changes = [
    { entity_type: 'item', change_type: 'changed', classification: 'possible_semantic', requires_manual_confirmation: true },
    { entity_type: 'item', change_type: 'added', classification: 'possible_semantic', requires_manual_confirmation: false },
    { entity_type: 'body', change_type: 'changed', classification: 'format_only', requires_manual_confirmation: false },
    { entity_type: 'award', change_type: 'removed', classification: 'possible_semantic', requires_manual_confirmation: true },
  ]
  assert.deepEqual(filterVersionChanges(changes, { entityType: 'item', changeType: 'changed', classification: 'possible_semantic', manualOnly: true }), [changes[0]])
  assert.deepEqual(filterVersionChanges(changes, { classification: 'format_only' }), [changes[2]])
  assert.deepEqual(filterVersionChanges(changes, { changeType: 'removed' }), [changes[3]])
  assert.deepEqual(filterVersionChanges(changes, { entityType: 'package' }), [])
  assert.equal(changes.length, 4)
  assert.deepEqual(filterVersionChanges(null), [])
})

test('old and new evidence keep their saved notice, candidate and version identities', () => {
  const change = { entity_type: 'item', entity_key: 'item:42',
    before_source: { notice_id: 8, candidate_id: 91, source_file: '旧表.pdf', source_location: 'page:1' },
    after_source: { notice_id: 9, candidate_id: 92, source_file: '新表.pdf', source_location: 'page:2' },
  }
  const context = { noticeId: 9, beforeVersionId: 'v-old', afterVersionId: 'v-new' }
  assert.deepEqual(versionEvidenceTarget(change, 'before', context), {
    notice_id: 8, item_id: 91, entity_type: 'item', source_file: '旧表.pdf', source_location: 'page:1', version_id: 'v-old',
  })
  assert.deepEqual(versionEvidenceTarget(change, 'after', context), {
    notice_id: 9, item_id: 92, entity_type: 'item', source_file: '新表.pdf', source_location: 'page:2', version_id: 'v-new',
  })
})

test('missing candidate provenance opens the version notice without guessing a candidate from entity_key', () => {
  const target = versionEvidenceTarget({ entity_type: 'item', entity_key: 'candidate:123' }, 'before', {
    noticeId: 99, beforeNoticeId: 20, beforeVersionId: 'frozen-version',
  })
  assert.equal(target.notice_id, 20)
  assert.equal(Object.hasOwn(target, 'item_id'), false)
  assert.equal(target.version_id, 'frozen-version')
  const bidder = versionEvidenceTarget({ entity_type: 'bidder', after_source: { notice_id: 99, candidate_id: 22, candidate_type: 'bid' } }, 'after')
  assert.equal(Object.hasOwn(bidder, 'item_id'), false)
  assert.equal(versionEvidenceTarget({}, 'after'), null)
  assert.equal(versionEvidenceTarget({}, 'outside', { noticeId: 20 }), null)
})

test('version labels distinguish current snapshots and uncertain identities, and preserve zero values', () => {
  assert.match(versionLabel({ version_id: 'v1', imported_at: '2026-10-11' }, 'v1'), /当前版本/)
  assert.match(versionLabel({ version_id: 'v0' }, 'v1'), /历史版本/)
  assert.match(versionIdentityLabel('identity_ambiguous'), /身份待确认/)
  assert.match(versionIdentityLabel('manual_link_required'), /人工关联/)
  assert.equal(displayVersionValue(0), '0')
  assert.equal(displayVersionValue(null), '—')
  assert.match(displayVersionValue({ name: '<script>alert(1)</script>' }), /<script>/)
})

test('frozen evidence paths accept only a saved version ID and reject arbitrary paths or query strings', () => {
  const id = '0123456789abcdef'.repeat(2)
  assert.equal(versionEvidencePath(id), `/api/v1/notice-versions/versions/${id}/evidence`)
  for (const invalid of [undefined, null, 10, '', id.toUpperCase(), `${id}?sql=delete`, '../notices/1', 'https://outside.test', `${id}/../../files`]) {
    assert.throws(() => versionEvidencePath(invalid), /版本 ID 格式无效/)
  }
})
