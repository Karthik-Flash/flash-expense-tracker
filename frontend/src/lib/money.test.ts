import assert from 'node:assert/strict'
import { test } from 'node:test'

import { groupIndian, percentOf, rupees } from './money.ts'

test('Indian grouping', () => {
  const cases: [number, string][] = [
    [0, '0'],
    [999, '999'],
    [1000, '1,000'],
    [99999, '99,999'],
    [100000, '1,00,000'],
    [1234567, '12,34,567'],
    [123456789, '12,34,56,789'],
  ]
  for (const [n, text] of cases) assert.equal(groupIndian(n), text)
})

test('whole rupees for overviews, rounded half away from zero', () => {
  assert.equal(rupees(0), '₹0')
  assert.equal(rupees(49), '₹0')
  assert.equal(rupees(50), '₹1')
  assert.equal(rupees(12345650), '₹1,23,457')
  assert.equal(rupees(12345649), '₹1,23,456')
  assert.equal(rupees(-150050), '−₹1,501')
  assert.equal(rupees(-150049), '−₹1,500')
})

test('a transaction: paise only when not zero (D-113)', () => {
  assert.equal(rupees(5, true), '₹0.05')
  assert.equal(rupees(99900, true), '₹999')
  assert.equal(rupees(99910, true), '₹999.10')
  assert.equal(rupees(12345678, true), '₹1,23,456.78')
  assert.equal(rupees(10000000, true), '₹1,00,000')
  assert.equal(rupees(-150050, true), '−₹1,500.50')
  assert.equal(rupees(0, true), '₹0')
})

test('money in and percentages', () => {
  assert.equal(rupees(45000, false, true), '+₹450')
  assert.equal(rupees(45025, true, true), '+₹450.25')
  assert.equal(rupees(45000, true, true), '+₹450')
  assert.equal(rupees(10000000, false, true), '+₹1,00,000')
  assert.equal(percentOf(250, 1000), '25%')
  assert.equal(percentOf(4, 1000), '<1%')
  assert.equal(percentOf(0, 1000), '0%')
  assert.equal(percentOf(5, 0), '')
})
