// Several users (5C): sign-up checks before sending, the first run once per login, and what
// Delete my account says. FAKE values only.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { deleteProblem, signUpProblem, welcomeDone, welcomeDue } from './account.ts'
import type { Snapshot } from './api/types.ts'

const memory = new Map<string, string>()
;(globalThis as { localStorage?: unknown }).localStorage = {
  getItem: (k: string) => memory.get(k) ?? null,
  setItem: (k: string, v: string) => void memory.set(k, v),
  removeItem: (k: string) => void memory.delete(k),
}

test('sign-up is checked before it is sent', () => {
  assert.equal(signUpProblem('tester@example.invalid', 'test-pass-1', 'abcd-efgh-jkmn'), '')
  assert.equal(signUpProblem('tester', 'test-pass-1', 'ABCDEFGHJKMN'), 'Enter your email address.')
  assert.equal(signUpProblem('t@example.invalid', 'short', 'ABCDEFGHJKMN'), 'Use a password of 8 to 72 characters.')
  assert.equal(signUpProblem('t@example.invalid', 'test-pass-1', 'ABCD'), 'An invite code has 12 letters and digits.')
})

test('the first run shows for an account with no data, once per login', () => {
  const empty = { transactions: [] } as unknown as Snapshot
  const full = { transactions: [{ id: 1 }] } as unknown as Snapshot
  assert.equal(welcomeDue(empty, 'user-new'), true)
  assert.equal(welcomeDue(full, 'user-new'), false)
  assert.equal(welcomeDue(null, 'user-new'), false)
  welcomeDone('user-new')
  assert.equal(welcomeDue(empty, 'user-new'), false)
  assert.equal(welcomeDue(empty, 'user-other'), true)
})

test('what Delete my account says', () => {
  assert.equal(deleteProblem({ status: 200, detail: null, message: '' }), '')
  assert.equal(deleteProblem({ status: 409, detail: 'admin_cannot_delete', message: 'x' }), 'The admin account cannot be deleted from the app.')
  assert.equal(deleteProblem({ status: 409, detail: 'fresh_login_required', message: 'x' }), 'Enter your password again, then try once more.')
  assert.equal(deleteProblem({ status: 503, detail: null, message: 'The server is not ready yet.' }), 'The server is not ready yet.')
})
