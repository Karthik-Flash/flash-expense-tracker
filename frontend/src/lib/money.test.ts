import assert from 'node:assert/strict'
import { test } from 'node:test'

import { groupIndian, moneyIn, percentOf, rupees, rupeesExact } from './money.ts'

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

test('paise for detail', () => {
  assert.equal(rupeesExact(5), '₹0.05')
  assert.equal(rupeesExact(99900), '₹999.00')
  assert.equal(rupeesExact(12345678), '₹1,23,456.78')
  assert.equal(rupeesExact(-150050), '−₹1,500.50')
})

test('money in and percentages', () => {
  assert.equal(moneyIn(45000), '+₹450')
  assert.equal(moneyIn(45025, true), '+₹450.25')
  assert.equal(percentOf(250, 1000), '25%')
  assert.equal(percentOf(4, 1000), '<1%')
  assert.equal(percentOf(0, 1000), '0%')
  assert.equal(percentOf(5, 0), '')
})
