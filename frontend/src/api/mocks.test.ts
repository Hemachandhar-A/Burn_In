import { describe, expect, test } from 'vitest'
import { MOCK_submitDisposition } from './mocks'

describe('MOCK_submitDisposition (the one route Block 5C left mocked)', () => {
  test('an empty rationale is rejected with a 422, never silently accepted', async () => {
    await expect(
      MOCK_submitDisposition('DUT-042', { verdict: 'REJECT', rationale: '  ' }, 'a.sharma'),
    ).rejects.toMatchObject({ status: 422 })
  })

  test('a valid submission echoes the request, stamped with the account and a timestamp', async () => {
    const record = await MOCK_submitDisposition(
      'DUT-042',
      { verdict: 'ACCEPT', rationale: 'Within tolerance.' },
      'r.mehta',
    )
    expect(record).toMatchObject({
      component_id: 'DUT-042',
      account_id: 'r.mehta',
      verdict: 'ACCEPT',
      rationale: 'Within tolerance.',
    })
    expect(Number.isNaN(Date.parse(record.timestamp))).toBe(false)
  })
})
