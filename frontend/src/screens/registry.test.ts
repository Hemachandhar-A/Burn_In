import { describe, expect, test } from 'vitest'
import { pathToLot, pathToPart, SCREENS } from './registry'

describe('screen registry', () => {
  test('screen ids and paths are unique', () => {
    expect(new Set(SCREENS.map((s) => s.id)).size).toBe(SCREENS.length)
    expect(new Set(SCREENS.map((s) => s.path)).size).toBe(SCREENS.length)
  })

  test('E6 step numbers run 1..7 in order', () => {
    expect(SCREENS.map((s) => s.e6Step)).toEqual([1, 2, 3, 4, 5, 6, 7])
  })
})

describe('pathToLot / pathToPart', () => {
  test('plain ids pass through', () => {
    expect(pathToLot('LOT-001')).toBe('/lots/LOT-001')
    expect(pathToPart('LOT-001-C0042')).toBe('/parts/LOT-001-C0042')
  })

  test('encode characters that would otherwise change the route', () => {
    expect(pathToPart('A/B')).toBe('/parts/A%2FB')
    expect(pathToPart('x#y')).toBe('/parts/x%23y')
    expect(pathToPart('q?r')).toBe('/parts/q%3Fr')
    expect(pathToLot('100%')).toBe('/lots/100%25')
  })

  test('encode dot-only ids so they are not read as relative path segments', () => {
    expect(pathToLot('.')).toBe('/lots/%2E')
    expect(pathToLot('..')).toBe('/lots/%2E%2E')
  })

  test.each(['', '   '])('reject a blank id (%j) instead of building a broken link', (id) => {
    expect(() => pathToLot(id)).toThrow(/lot id/)
    expect(() => pathToPart(id)).toThrow(/component id/)
  })
})
