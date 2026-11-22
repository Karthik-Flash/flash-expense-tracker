// Several users (5C, D-128 to D-132): the pure parts of sign-up, the first run and Delete my
// account. Tested in Node (account.test.ts).

import type { SendAnswer } from './api/client.ts'
import type { Snapshot } from './api/types.ts'

/** What is wrong with a sign-up before it is sent; '' when it can go. */
export function signUpProblem(email: string, password: string, code: string): string {
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) return 'Enter your email address.'
  if (password.length < 8 || password.length > 72) return 'Use a password of 8 to 72 characters.'
  if (code.toUpperCase().replace(/[^A-Z0-9]/g, '').length !== 12) return 'An invite code has 12 letters and digits.'
  return ''
}

const WELCOME = 'flash-welcome-done:'

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

/** The first run (D-132): an account with no data yet, once per login on this device. */
export function welcomeDue(snapshot: Snapshot | null, user: string | null): boolean {
  if (!snapshot || !user || snapshot.transactions.length > 0) return false
  try {
    return storage()?.getItem(WELCOME + user) !== '1'
  } catch {
    return false
  }
}

export function welcomeDone(user: string | null): void {
  try {
    if (user) storage()?.setItem(WELCOME + user, '1')
  } catch {
    // private window: it may show again next time
  }
}

/** The server's answer to Delete my account, in plain words; '' when the account is gone. */
export function deleteProblem(answer: SendAnswer): string {
  if (answer.status === 200) return ''
  if (answer.detail === 'admin_cannot_delete') return 'The admin account cannot be deleted from the app.'
  if (answer.detail === 'fresh_login_required') return 'Enter your password again, then try once more.'
  return answer.message || 'Could not delete the account. Try again.'
}

