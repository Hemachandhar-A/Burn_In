// @vitest-environment node
import { describe, expect, test } from 'vitest'
// @ts-ignore - the app tsconfig carries no Node types (and no new dependency is allowed); vitest runs this in Node.
import { readFileSync } from 'node:fs'

const css: string = readFileSync('src/index.css', 'utf-8')

// jsdom does no layout, so the overflow found in the 7b rehearsal (the long confidence qualifier ran past the
// Diagnostic card and widened the page) is pinned at the stylesheet: the chip must be allowed to wrap and be capped.
describe('confidence qualifier chip', () => {
  const rule = css.match(/\.confidence-chip\s*\{([^}]*)\}/)?.[1] ?? ''
  test('may wrap instead of forcing a single line', () => {
    expect(rule).toMatch(/white-space:\s*normal/)
  })
  test('is capped to part of the card header and breaks long words', () => {
    expect(rule).toMatch(/max-width:\s*\d+%/)
    expect(rule).toMatch(/overflow-wrap:\s*anywhere/)
  })
})
