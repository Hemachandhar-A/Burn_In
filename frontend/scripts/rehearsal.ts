/**
 * G7 rehearsal: drives the single-process demo (scripts/build_demo.sh) through demo_data/README.md's click path
 * with a real Chromium. Plain Node (type stripping), no imports from ../src:
 *
 *   BASE_URL=http://localhost:8030 RUN=run1 node scripts/rehearsal.ts
 *
 * Writes PNGs to frontend/screenshots/rehearsal/<RUN>/, the downloaded report to the same folder, a JSON step table
 * (steps.json), the visible text of the key screens (text-*.txt) and console-errors.txt. Every step records seconds,
 * the console errors raised during it and a note; a failing step is recorded and the run continues.
 */
import { chromium } from '@playwright/test'
import type { Page } from '@playwright/test'
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..', '..')
const BASE = (process.env.BASE_URL || 'http://localhost:8030').replace(/\/+$/, '')
const RUN = process.env.RUN || 'run1'
const OUT = path.join(ROOT, 'frontend', 'screenshots', 'rehearsal', RUN)
const DEMO = path.join(ROOT, 'demo_data')
const TODAY = new Date().toISOString().slice(0, 10)
const COMPLETE = 'DEMO-COMPLETE-01'
const EARLY = 'DEMO-EARLY-01'
const LIVE = 'LIVE-01'

interface StepRow {
  step: string
  result: 'OK' | 'FAIL'
  seconds: number
  consoleErrors: number
  notes: string
}
const rows: StepRow[] = []
const consoleErrors: string[] = []
let current = 'startup'

async function main() {
  await mkdir(OUT, { recursive: true })
  const browser = await chromium.launch()
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true })
  const page = await context.newPage()
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(`[${current}] ${m.text()}`)
  })
  page.on('pageerror', (e) => consoleErrors.push(`[${current}] pageerror: ${e.message}`))

  const shot = async (name: string, fullPage = true) => {
    await page.waitForTimeout(500)
    await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage })
  }
  const dump = async (name: string) => {
    const text = await page.locator('body').innerText()
    await writeFile(path.join(OUT, `text-${name}.txt`), text)
    return text
  }

  async function step(name: string, fn: (notes: string[]) => Promise<void>) {
    current = name
    const before = consoleErrors.length
    const notes: string[] = []
    const t0 = performance.now()
    let result: 'OK' | 'FAIL' = 'OK'
    try {
      await fn(notes)
    } catch (e) {
      result = 'FAIL'
      notes.push(`ERROR: ${(e instanceof Error ? e.message : String(e)).split('\n')[0].slice(0, 300)}`)
      try {
        await page.screenshot({ path: path.join(OUT, `FAIL-${name.replace(/\W+/g, '-')}.png`), fullPage: true })
      } catch {
        /* ignore */
      }
    }
    const seconds = Number(((performance.now() - t0) / 1000).toFixed(1))
    rows.push({ step: name, result, seconds, consoleErrors: consoleErrors.length - before, notes: notes.join(' | ') })
    console.log(`${result} ${seconds}s  ${name}  ${notes.join(' | ')}`)
  }

  async function signIn(label: string, pin: string) {
    await page.goto(`${BASE}/#/login`)
    await page.waitForSelector('text=Sign In')
    await page.getByLabel(label).check()
    await page.getByLabel('PIN').fill(pin)
    await page.getByRole('button', { name: /^sign in$/i }).click()
    await page.waitForURL((u) => !u.hash.includes('/login'))
  }
  async function signOut() {
    await page.getByRole('button', { name: 'Account menu' }).click()
    await page.getByRole('button', { name: 'Sign out' }).click()
    await page.waitForSelector('text=Sign In')
  }
  async function fillMetadata(lotId: string) {
    await page.getByLabel('Lot ID').fill(lotId)
    await page.getByLabel('Part Number').fill('DEMO-PN')
    await page.getByLabel('Manufacturer').fill('Northvale Semiconductor')
    await page.getByLabel('Date Code').fill('2603')
    await page.getByLabel('Test Date').fill(TODAY)
  }
  async function ingest(fileInput: 'Lot CSV file' | 'Checkpoint CSV file', file: string, lotId: string, notes: string[], shotName: string) {
    await page.goto(`${BASE}/#/ingest`)
    await page.waitForSelector('h1.screen-title')
    await fillMetadata(lotId)
    await page.getByLabel(fileInput).setInputFiles(path.join(DEMO, file))
    await shot(shotName, false)
    await page.getByRole('button', { name: 'Commit Batch' }).click()
    await page.waitForSelector('section[aria-label="Ingestion result"], .form-error[role=alert]', { timeout: 120000 })
    const failed = await page.locator('.form-error[role=alert]').count()
    if (failed) notes.push(`ingest error: ${(await page.locator('.form-error[role=alert]').first().innerText()).slice(0, 200)}`)
    notes.push(`result: ${(await page.locator('section[aria-label="Ingestion result"]').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 220)}`)
  }
  /** Opens a lot dashboard; returns [first paint, settled] visible summary so a stale first paint is visible. */
  async function openLot(lotId: string): Promise<[string, string]> {
    await page.goto(`${BASE}/#/lots/${encodeURIComponent(lotId)}`)
    await page.waitForSelector('text=/PDA:/', { timeout: 120000 })
    const summary = async () =>
      (await page.locator('.summary-grid, .lot-summary, section.screen').first().innerText()).replace(/\s+/g, ' ').match(/OVERALL VERDICT.{0,120}?PDA: [\d.]+%/i)?.[0] ?? '?'
    const first = await summary()
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1200)
    return [first, await summary()]
  }

  const t0All = performance.now()
  let reportDoneAt = 0
  let topPart = ''

  await step('01 login as a.sharma', async () => {
    await page.goto(`${BASE}/#/login`)
    await page.waitForSelector('text=Sign In')
    await shot('01-login', false)
    await page.getByLabel('A. Sharma').check()
    await page.getByLabel('PIN').fill('1234')
    await page.getByRole('button', { name: /^sign in$/i }).click()
    await page.waitForURL((u) => !u.hash.includes('/login'))
  })

  await step('02 project browser lists both lots', async (notes) => {
    await page.goto(`${BASE}/#/projects`)
    await page.waitForLoadState('networkidle')
    await page.waitForSelector(`text=${COMPLETE}`, { timeout: 30000 })
    const text = await dump('projects')
    notes.push(`${COMPLETE}: ${text.includes(COMPLETE)}; ${EARLY}: ${text.includes(EARLY)}`)
    if (!text.includes(EARLY)) throw new Error(`${EARLY} missing`)
    await shot('02-project-browser')
  })

  await step('03 open DEMO-COMPLETE-01 dashboard', async (notes) => {
    await page.getByRole('link', { name: COMPLETE }).first().click()
    await page.waitForSelector('text=/PDA:/', { timeout: 120000 })
    const text = await dump('dashboard-complete')
    notes.push(text.replace(/\s+/g, ' ').match(/Overall Verdict.{0,60}/i)?.[0] ?? 'no verdict text')
    notes.push(text.match(/PDA: [\d.]+%/)?.[0] ?? 'no PDA')
    const first = page.locator('.ranked-list').first().locator('tbody tr td a').first()
    topPart = (await first.innerText().catch(() => '')) || ''
    const lastLink = await page.locator('.ranked-list').first().locator('tbody tr td a').last().innerText().catch(() => '')
    notes.push(`first row of "By Outlier Severity": ${topPart}; last row: ${lastLink}`)
    await shot('03-lot-dashboard-complete')
  })

  await step('04 generate DPA work order', async (notes) => {
    await page.getByRole('button', { name: /generate dpa work order/i }).click()
    await page.waitForSelector('text=DPA Work Order', { timeout: 60000 })
    const t = (await page.locator('.dpa-result').innerText()).replace(/\s+/g, ' ')
    notes.push(t.slice(0, 400))
    await shot('04-dpa-work-order')
  })

  await step('05 open top part (first row of By Outlier Severity)', async (notes) => {
    await page.locator('.ranked-list').first().locator('tbody tr td a').first().click()
    await page.waitForSelector('h1.screen-title')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1500)
    const text = await dump('part-detail')
    notes.push(`url ${page.url().split('#')[1]}`)
    notes.push(`plotly charts: ${await page.locator('.js-plotly-plot').count()}`)
    await shot('05-part-detail-top')
    void text
  })
  const partUrl = () => page.url()

  let partHash = ''
  await step('06 sign-offs: a.sharma, same-account repeat, r.mehta', async (notes) => {
    partHash = new URL(partUrl()).hash
    const rationale = page.getByLabel(/Technical Disposition Rationale/)
    await rationale.fill('Leakage drift confirmed at 24h.')
    await page.getByRole('button', { name: 'Reject', exact: true }).click()
    await page.waitForSelector('text=/1 sign-off.s. recorded by distinct accounts/')
    await shot('06a-first-signoff')
    // same account again
    await rationale.fill('Second attempt by the same account.')
    await page.getByRole('button', { name: 'Reject', exact: true }).click()
    await page.waitForSelector('[role=alert]', { timeout: 15000 })
    const msg = (await page.locator('[role=alert]').first().innerText()).replace(/\s+/g, ' ')
    notes.push(`same-account message: ${msg.slice(0, 200)}`)
    await shot('06b-same-account-message')
    await signOut()
    await signIn('R. Mehta', '5678')
    await page.goto(`${BASE}/${partHash}`)
    await page.waitForSelector('h1.screen-title')
    await page.getByLabel(/Technical Disposition Rationale/).fill('Concur: reject.')
    await page.getByRole('button', { name: 'Reject', exact: true }).click()
    await page.waitForSelector('text=/2 sign-off.s. recorded by distinct accounts/')
    await shot('06c-second-signoff')
  })

  await step('07 confirmed outcome + settings worklist', async (notes) => {
    await signOut()
    await signIn('A. Sharma', '1234')
    await page.goto(`${BASE}/#/settings`)
    await page.waitForSelector('text=Corrective Feedback Status')
    await page.waitForSelector('text=Worklist')
    await page.waitForLoadState('networkidle')
    await page.waitForFunction(() => !document.body.innerText.includes('Loading worklist'), null, { timeout: 30000 })
    const before = (await dump('settings-before-outcome')).replace(/\s+/g, ' ')
    await shot('07a-settings-before-outcome')
    await page.goto(`${BASE}/${partHash}`)
    await page.waitForSelector('h1.screen-title')
    await page.getByRole('button', { name: 'Record Confirmed Outcome' }).click()
    await page.getByLabel('Confirmed Outcome').selectOption('Confirmed Defective')
    await page.getByRole('button', { name: 'Confirm', exact: true }).click()
    await page.waitForSelector('text=/Confirmed Defective .* recorded by/')
    await shot('07b-confirmed-outcome-recorded')
    await page.goto(`${BASE}/#/settings`)
    await page.waitForSelector('text=Corrective Feedback Status')
    await page.waitForLoadState('networkidle')
    await page.waitForFunction(() => !document.body.innerText.includes('Loading worklist'), null, { timeout: 30000 })
    await page.waitForTimeout(1000)
    const after = (await dump('settings-after-outcome')).replace(/\s+/g, ' ')
    await shot('07c-settings-after-outcome')
    const wl = (s: string) => s.match(/Dispositions awaiting.*?Lot Dashboard\.\s*(.{0,120})/)?.[1]?.trim() ?? 'no worklist text'
    notes.push(`before: ${wl(before)}`)
    notes.push(`after: ${wl(after)}`)
    notes.push(`status: ${after.match(/each time this screen opens\.\s*(.{0,110})/)?.[1] ?? 'status text not found'}`)
  })

  await step('08 ingest live_0h_24h.csv as LIVE-01', async (notes) => {
    await ingest('Lot CSV file', 'live_0h_24h.csv', LIVE, notes, '08a-ingest-form-lot-0h-24h')
    const [f8, s8] = await openLot(LIVE)
    notes.push(`first paint: ${f8}`)
    notes.push(`settled: ${s8}`)
    const text = (await dump('dashboard-live-0h24h')).replace(/\s+/g, ' ')
    notes.push(text.match(/Overall Verdict.{0,50}/i)?.[0] ?? 'no verdict')
    notes.push(`Forecast chip: ${(await page.locator('.forecast-chip').count()) > 0}`)
    await shot('08b-live-dashboard-in-progress')
  })

  await step('09 upload live_96h.csv as checkpoint', async (notes) => {
    await ingest('Checkpoint CSV file', 'live_96h.csv', LIVE, notes, '09a-ingest-form-checkpoint-96h')
    const [f9, s9] = await openLot(LIVE)
    notes.push(`first paint: ${f9}`)
    notes.push(`settled: ${s9}`)
    const text = (await dump('dashboard-live-96h')).replace(/\s+/g, ' ')
    notes.push(text.match(/Overall Verdict.{0,50}/i)?.[0] ?? 'no verdict')
    notes.push(`PDA ${text.match(/PDA: [\d.]+%/)?.[0]}`)
    await shot('09-live-dashboard-after-96h')
  })

  await step('10 upload live_168h.csv as checkpoint -> complete', async (notes) => {
    await ingest('Checkpoint CSV file', 'live_168h.csv', LIVE, notes, '10a-ingest-form-checkpoint-168h')
    const [f10, s10] = await openLot(LIVE)
    notes.push(`first paint: ${f10}`)
    notes.push(`settled: ${s10}`)
    const text = (await dump('dashboard-live-168h')).replace(/\s+/g, ' ')
    notes.push(text.match(/Overall Verdict.{0,50}/i)?.[0] ?? 'no verdict')
    notes.push(`PDA ${text.match(/PDA: [\d.]+%/)?.[0]}; Forecast chip: ${(await page.locator('.forecast-chip').count()) > 0}`)
    const rowsA = await page.locator('.ranked-list').first().locator('tbody tr').count()
    notes.push(`Module A ranking rows: ${rowsA}`)
    if (rowsA === 0) throw new Error('Module A ranking did not appear')
    await shot('10-live-dashboard-complete')
  })

  await step('11 download report PDF', async (notes) => {
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 120000 }),
      page.getByRole('button', { name: /generate report/i }).click(),
    ])
    const file = path.join(OUT, download.suggestedFilename() || 'report.pdf')
    await download.saveAs(file)
    const buf = await readFile(file)
    const size = (await stat(file)).size
    notes.push(`${path.basename(file)}: ${size} bytes, header ${JSON.stringify(buf.subarray(0, 5).toString('latin1'))}`)
    if (!buf.subarray(0, 4).toString('latin1').startsWith('%PDF')) throw new Error('not a PDF')
    if (size <= 10 * 1024) throw new Error(`PDF only ${size} bytes`)
    await shot('11-after-report-download', false)
    reportDoneAt = performance.now()
  })

  await step('12 history shows the events', async (notes) => {
    await page.goto(`${BASE}/#/history`)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1000)
    const text = await dump('history')
    for (const k of ['Ingest', 'Checkpoint Added', 'Analysis Run', 'Disposition', 'Timing Flag', 'Sign-offs occurred']) {
      notes.push(`${k}: ${new RegExp(k, 'i').test(text)}`)
    }
    await shot('12-history')
  })

  await step('13 hard refresh lands on login', async (notes) => {
    await page.reload()
    await page.waitForSelector('text=Sign In')
    notes.push(`url after reload: ${page.url().split('#')[1]}`)
    if (!/#\/login/.test(page.url())) throw new Error('not on login after reload')
    await shot('13-after-hard-refresh', false)
  })

  await step('14 request failure shows a visible error', async (notes) => {
    await signIn('A. Sharma', '1234')
    const pattern = `**/lots/${COMPLETE}`
    await page.route(pattern, (route) => route.abort())
    await page.goto(`${BASE}/#/lots/${COMPLETE}`)
    await page.waitForSelector('[role=alert]', { timeout: 60000 })
    notes.push(`alert: ${(await page.locator('[role=alert]').first().innerText()).replace(/\s+/g, ' ').slice(0, 160)}`)
    await shot('14-error-state', false)
    await page.unroute(pattern)
  })

  await browser.close()
  const total = ((reportDoneAt - t0All) / 1000 / 60).toFixed(2)
  await writeFile(path.join(OUT, 'steps.json'), JSON.stringify({ rows, loginToReportMinutes: total }, null, 2))
  await writeFile(
    path.join(OUT, 'console-errors.txt'),
    consoleErrors.length ? consoleErrors.join('\n') + '\n' : 'No console errors or uncaught page errors.\n',
  )
  console.log(`\nlogin -> report (script time incl. waits): ${total} min; console errors: ${consoleErrors.length}`)
  console.log(`failed steps: ${rows.filter((r) => r.result === 'FAIL').map((r) => r.step).join('; ') || 'none'}`)
}

main().catch((e) => {
  console.error(e)
  process.exitCode = 1
})
// Page type is used only for helper signatures above.
export type { Page }
