/**
 * A failed API call, carrying every message the server gave rather than just the first. E7 step 5
 * asks for visible, specific validation errors, and ingestion returns a list of them.
 */
export class ApiError extends Error {
  readonly status: number
  readonly messages: string[]

  constructor(status: number, messages: string[]) {
    super(messages.join('\n'))
    this.name = 'ApiError'
    this.status = status
    this.messages = messages
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** FastAPI's own 422 item (`ValidationError`): where it failed, and why. */
function validationItemMessage(item: Record<string, unknown>): string | null {
  if (typeof item.msg !== 'string') return null
  const loc = Array.isArray(item.loc) ? item.loc.filter((p) => p !== 'body').join('.') : ''
  return loc ? `${loc}: ${item.msg}` : item.msg
}

/**
 * Every shape a FastAPI error body takes in this backend, flattened to readable lines:
 * - `{detail: "lot 'X' already exists ..."}`: an HTTPException with a message (409, 404)
 * - `{detail: ["line 3: value 'x' is not a number", ...]}`: ingestion's own validation list
 * - `{detail: [{loc, msg, type}, ...]}`: FastAPI's request validation (`HTTPValidationError`)
 */
export function errorMessages(body: unknown, status: number): string[] {
  const detail = isRecord(body) ? body.detail : undefined
  if (typeof detail === 'string' && detail.trim()) return [detail]
  if (Array.isArray(detail)) {
    const lines = detail
      .map((item) =>
        typeof item === 'string' ? item : isRecord(item) ? validationItemMessage(item) : null,
      )
      .filter((line): line is string => !!line && line.trim() !== '')
    if (lines.length > 0) return lines
  }
  return [`The server answered ${status} with no further detail.`]
}

/** Turns whatever a call threw (ApiError, a network failure, anything) into lines to show. */
export function describeFailure(error: unknown): string[] {
  if (error instanceof ApiError) return error.messages
  // fetch() rejects with a TypeError when the server can't be reached at all.
  if (error instanceof TypeError) {
    return ['Could not reach the API server. Check that the backend is running.']
  }
  return [error instanceof Error && error.message ? error.message : 'Something went wrong.']
}
