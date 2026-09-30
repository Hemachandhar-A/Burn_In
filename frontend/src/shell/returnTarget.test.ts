import { describe, expect, test } from 'vitest'
import { returnTarget } from './returnTarget'

const HOME = '/ingest'

describe('returnTarget', () => {
  test('returns the remembered page with its query and hash', () => {
    const state = { from: { pathname: '/lots/LOT-7', search: '?v=1', hash: '#top' } }
    expect(returnTarget(state, HOME)).toBe('/lots/LOT-7?v=1#top')
  })

  test.each([
    ['no state (a direct visit to Login)', null],
    ['undefined state', undefined],
    ['state without from', {}],
    ['a non-object state', 'lots'],
    ['a non-string pathname', { from: { pathname: 42 } }],
    ['a relative pathname', { from: { pathname: 'lots/LOT-7' } }],
    ['a protocol-relative pathname', { from: { pathname: '//evil.test/x' } }],
    ['Login itself (would loop)', { from: { pathname: '/login' } }],
    ['Login with a trailing slash', { from: { pathname: '/login/' } }],
  ])('falls back to home for %s', (_label, state) => {
    expect(returnTarget(state, HOME)).toBe(HOME)
  })

  test('tolerates missing or non-string search/hash', () => {
    expect(returnTarget({ from: { pathname: '/history', search: 5 } }, HOME)).toBe('/history')
  })
})
