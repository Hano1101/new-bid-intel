import assert from 'node:assert/strict'
import test from 'node:test'
import {
  hasReviewSourceEvidence,
  reviewCandidateKey,
  reviewCorrectionValues,
  reviewEvidenceTarget,
  reviewPackageLabel,
  reviewSourceEvidence,
  reviewWarningDetails,
} from '../src/utils/reviewQueue.js'

test('review cards label a default package and missing source excerpt plainly', () => {
  assert.equal(reviewPackageLabel('default'), 'default（系统默认值）')
  assert.equal(reviewPackageLabel('A-03'), 'A-03')
  assert.equal(reviewPackageLabel(null), '未保存')
  assert.equal(reviewSourceEvidence({ source_evidence: '' }), '无来源片段')
  assert.equal(reviewSourceEvidence({ source_evidence: '   ' }), '无来源片段')
  assert.equal(hasReviewSourceEvidence({ source_evidence: '   ' }), false)
  assert.equal(hasReviewSourceEvidence({ source_evidence: ' 原文片段 ' }), true)
  assert.equal(reviewSourceEvidence({ source_evidence: '投标人：示例单位' }), '投标人：示例单位')
})

test('evidence jump opens the notice and selects the exact item when available', () => {
  assert.deepEqual(reviewEvidenceTarget({ candidate_type: 'item', candidate_id: 17, notice_id: 4 }), {
    noticeId: 4, itemId: 17,
  })
  assert.deepEqual(reviewEvidenceTarget({ candidate_type: 'award', candidate_id: 8, notice_id: 4 }), {
    noticeId: 4, itemId: null,
  })
})

test('review cards surface OCR and attachment warning explanations', () => {
  const row = { reasons: [
    { code: 'field_missing', detail: '标的字段为空' },
    { code: 'parsing_warning', detail: '关联公告有 OCR 告警：扫描页未识别' },
    { code: 'parsing_warning', detail: '关联公告有附件告警：附件展开失败' },
  ] }
  assert.deepEqual(reviewWarningDetails(row), [
    '关联公告有 OCR 告警：扫描页未识别',
    '关联公告有附件告警：附件展开失败',
  ])
})

test('corrections submit only changed values and leave untouched missing fields alone', () => {
  const original = {
    package_code: null,
    product_name: '设备甲',
    category: null,
    brand: null,
    quantity: null,
  }
  const draft = {
    package_code: '',
    product_name: '设备乙',
    category: '',
    brand: '',
    quantity: '',
  }
  assert.deepEqual(reviewCorrectionValues(draft, original), { product_name: '设备乙' })
  assert.deepEqual(reviewCorrectionValues({ brand: '' }, { brand: '旧品牌' }), { brand: null })
})

test('replaced candidates get separate history cache identities even when IDs are reused', () => {
  assert.notEqual(
    reviewCandidateKey({ candidate_type: 'item', candidate_id: 3, candidate_epoch: 1 }),
    reviewCandidateKey({ candidate_type: 'item', candidate_id: 3, candidate_epoch: 2 }),
  )
})
