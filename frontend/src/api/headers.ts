// Every request header and method the app sends to the API (D-104). The API is on another
// origin, so the browser asks it first (a CORS preflight) and blocks anything it does not
// allow. backend/app/main.py allows exactly these; backend/tests/test_cors.py reads this
// file, so a header added on one side only fails the tests.
export const HEADER = {
  authorization: 'Authorization',
  accept: 'Accept',
  contentType: 'Content-Type',
  ifNoneMatch: 'If-None-Match',
  idempotencyKey: 'Idempotency-Key',
  deferRecompute: 'X-Defer-Recompute',
} as const

export const METHODS = ['GET', 'PUT', 'POST', 'DELETE'] as const

/** Response headers the app reads. */
export const EXPOSED = ['ETag'] as const
