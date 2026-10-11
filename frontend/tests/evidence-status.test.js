import test from 'node:test'
import assert from 'node:assert/strict'
import { fieldEvidenceLabel } from '../src/utils/evidenceStatus.js'

test('new explicit omissions, source blanks, and legacy unknown values stay distinct', () => {
  assert.equal(
    fieldEvidenceLabel('explicitly_not_published', null, true, true),
    '原文明示未公示',
  )
  assert.equal(
    fieldEvidenceLabel('blank_in_source', null, true, true),
    '原文对应字段留空；不能判定为未公示',
  )
  assert.equal(
    fieldEvidenceLabel(undefined, null, false),
    '无值 · 状态未知，待核验',
  )
})

test('a value without field-level provenance is not described as source-verified', () => {
  assert.equal(
    fieldEvidenceLabel('present', '某采购中心', false),
    '已提取 · 字段来源待核验',
  )
  assert.equal(
    fieldEvidenceLabel('present', '某采购中心', true),
    '有记录级片段；未保存字段级对应关系',
  )
})

test('empty and explicit-unpublished states require field-level evidence and cannot contradict values', () => {
  assert.equal(
    fieldEvidenceLabel('blank_in_source', null, true, true),
    '原文对应字段留空；不能判定为未公示',
  )
  assert.equal(
    fieldEvidenceLabel('explicitly_not_published', null, false, false),
    '无值 · 缺少字段证据，待核验',
  )
  assert.equal(
    fieldEvidenceLabel('blank_in_source', '有抽取值', true, true),
    '有值 · 来源状态冲突，待核验',
  )
})
