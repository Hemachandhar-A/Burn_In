/**
 * Screenshot capture for Block 5C Part 4, extended in Block 5D Part 4 (14 screenshots, console-error log, hard-refresh check). Starts `vite dev` on its own port (not the app's
 * normal dev port, so it doesn't collide with a real dev session), pointed at this worktree's own
 * backend (default http://localhost:8001; override with VITE_API_BASE_URL), drives it with a real
 * Chromium via Playwright, and writes 1440x900 PNGs into frontend/screenshots/.
 *
 * Reuses whatever lots already exist in the backend (loaded once by scripts/smoke_live.ts - Part
 * 1b: loading the demo lot is slow, load it once and reuse it) rather than uploading again: finds
 * the demo lot (part_number "DEMO-PN") and the small in-progress lot smoke_live.ts creates
 * (part_number "SMOKE-PN") via the app's own typed client, the same way the app itself would.
 *
 *   npx tsx scripts/screenshots.ts
 *
 * BASE_URL mode (Session 6): `BASE_URL=http://localhost:8020 npx tsx scripts/screenshots.ts` skips vite entirely and
 * captures the production build served by FastAPI itself (scripts/build_demo.sh) - same origin for page and API -
 * of the two demo lots (DEMO-COMPLETE-01, DEMO-EARLY-01) into frontend/screenshots/single-process/.
 */
import { chromium } from '@playwright/test'
import { execFileSync, spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { login } from '../src/api/auth'
import { createApiClient } from '../src/api/client'
import { getLotSummary } from '../src/api/lotDetail'
import { listProjects } from '../src/api/lots'
import { getPartDetail } from '../src/api/parts'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND_ROOT = path.resolve(__dirname, '..')
const SCREENSHOT_DIR = path.join(FRONTEND_ROOT, 'screenshots')
// Must be 5173 - api/main.py's CORSMiddleware hardcodes VITE_DEV_ORIGINS to exactly
// http://localhost:5173 / http://127.0.0.1:5173 (the Vite default), not configurable from
// frontend/. A different port here fails every request with a CORS-shaped network error.
const VITE_PORT = 5173
const APP_URL = `http://localhost:${VITE_PORT}`
const API_BASE_URL = process.env.VITE_API_BASE_URL || 'http://localhost:8001'

function waitForServer(url: string, timeoutMs = 30000): Promise<void> {
  const start = Date.now()
  return new Promise((resolve, reject) => {
    const check = () => {
      fetch(url)
        .then(() => resolve())
        .catch(() => {
          if (Date.now() - start > timeoutMs) {
            reject(new Error(`server at ${url} did not start within ${timeoutMs}ms`))
          } else {
            setTimeout(check, 400)
          }
        })
    }
    check()
  })
}

async function singleProcess(baseUrl: string) {
  const outDir = path.join(SCREENSHOT_DIR, 'single-process')
  await mkdir(outDir, { recursive: true })
  const complete = 'DEMO-COMPLETE-01'
  const early = 'DEMO-EARLY-01'

  let apiToken: string | null = null
  const apiClient = createApiClient({ baseUrl, getToken: () => apiToken })
  apiToken = (await login(apiClient, { account_id: 'a.sharma', pin: '1234' })).access_token
  const completeSummary = await getLotSummary(apiClient, complete)
  // module_a_rank is a position: 1 = most severe. Module A REJECT parts of the complete lot, most severe first.
  const aRejects = completeSummary.assessments
    .filter((a) => a.verdict === 'REJECT' && a.module_a_ran)
    .sort((x, y) => x.module_a_rank - y.module_a_rank)
  if (aRejects.length < 2) throw new Error(`${complete} has fewer than 2 Module A REJECT parts`)
  console.log(`Complete lot top part: ${aRejects[0].component_id}, second: ${aRejects[1].component_id}`)
  const earlySummary = await getLotSummary(apiClient, early)
  const earlyRejects = earlySummary.assessments.filter((a) => a.verdict === 'REJECT')
  if (earlyRejects.length === 0) throw new Error(`${early} has no REJECT part`)
  // module_b_rank is a position: 1 = most severe.
  const earlyPart = earlyRejects.reduce((best, a) => (a.module_b_rank < best.module_b_rank ? a : best))
  console.log(`Early REJECT part: ${earlyPart.component_id}`)

  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  let currentScreen = 'startup'
  const consoleErrors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(`[${currentScreen}] console.error: ${msg.text()}`)
  })
  page.on('pageerror', (err) => consoleErrors.push(`[${currentScreen}] pageerror: ${err.message}`))
  const shot = async (name: string) => {
    await page.waitForTimeout(400)
    await page.screenshot({ path: path.join(outDir, `${name}.png`) })
    console.log(`  captured single-process/${name}.png`)
  }

  try {
    currentScreen = 'login'
    await page.goto(`${baseUrl}/#/login`)
    await page.waitForSelector('text=Sign In')
    await shot('01-login')
    await page.getByLabel('A. Sharma').check()
    await page.getByLabel('PIN').fill('1234')
    await page.getByRole('button', { name: /^sign in$/i }).click()
    await page.waitForURL((url) => !url.hash.includes('/login'))

    currentScreen = 'project browser'
    await page.goto(`${baseUrl}/#/projects`)
    await page.waitForLoadState('networkidle')
    await shot('02-project-browser')

    currentScreen = 'lot dashboard golden'
    await page.goto(`${baseUrl}/#/lots/${complete}`)
    await page.waitForSelector('text=/PDA:/')
    const dpaButton = page.getByRole('button', { name: /generate dpa work order/i })
    if (await dpaButton.isVisible()) {
      await dpaButton.click()
      await page.waitForSelector('text=DPA Work Order')
    }
    await shot('03-lot-dashboard-complete')

    currentScreen = 'lot dashboard early'
    await page.goto(`${baseUrl}/#/lots/${early}`)
    await page.waitForSelector('text=/PDA:/')
    await shot('04-lot-dashboard-early')

    currentScreen = 'part detail top Module A REJECT'
    await page.goto(`${baseUrl}/#/parts/${encodeURIComponent(aRejects[0].component_id)}`)
    await page.waitForSelector('h1.screen-title')
    await shot('05-part-detail-module-a-reject')

    currentScreen = 'part detail early'
    await page.goto(`${baseUrl}/#/parts/${encodeURIComponent(earlyPart.component_id)}`)
    await page.waitForSelector('h1.screen-title')
    await shot('06-part-detail-early-reject')

    currentScreen = 'settings'
    await page.goto(`${baseUrl}/#/settings`)
    await page.waitForSelector('text=Corrective Feedback Status')
    await shot('07-settings')

    currentScreen = 'part detail second Module A REJECT'
    await page.goto(`${baseUrl}/#/parts/${encodeURIComponent(aRejects[1].component_id)}`)
    await page.waitForSelector('h1.screen-title')
    await shot('08-part-detail-module-a-reject-second')
  } finally {
    await browser.close()
    await writeFile(
      path.join(outDir, 'console-errors.txt'),
      consoleErrors.length > 0
        ? consoleErrors.join('\n') + '\n'
        : 'No console errors or uncaught page errors.\n',
    )
    console.log(`Console errors recorded: ${consoleErrors.length}`)
  }
}

async function main() {
  if (process.env.BASE_URL) return singleProcess(process.env.BASE_URL.replace(/\/+$/, ''))
  await mkdir(SCREENSHOT_DIR, { recursive: true })

  // Discover the already-loaded lots (real typed client, not the browser - rule 14 applies to
  // this script's own API calls too).
  let apiToken: string | null = null
  const apiClient = createApiClient({ baseUrl: API_BASE_URL, getToken: () => apiToken })
  const session = await login(apiClient, { account_id: 'a.sharma', pin: '1234' })
  apiToken = session.access_token
  const projects = await listProjects(apiClient)
  const demoProject = projects.find((p) => p.part_number === 'DEMO-PN')
  const inProgressProject = projects.find((p) => p.part_number === 'SMOKE-PN')
  if (!demoProject || !inProgressProject) {
    throw new Error(
      'demo lot (DEMO-PN) or in-progress lot (SMOKE-PN) not found - run scripts/smoke_live.ts first',
    )
  }
  const demoSummary = await getLotSummary(apiClient, demoProject.lot_id)
  const flagged = demoSummary.assessments.filter((a) => a.verdict !== 'PASS')
  const flaggedComponent = flagged.reduce((best, a) => (a.module_a_rank > best.module_a_rank ? a : best))
  // A flagged part with no sign-offs yet, so screenshots 06/10/11 show the same part before, after
  // the first and after the second sign-off (smoke_live.ts already dispositioned the top one).
  const byRank = [...flagged].sort((a, b) => b.module_a_rank - a.module_a_rank)
  let freshComponent = flaggedComponent
  for (const candidate of byRank) {
    const detail = await getPartDetail(apiClient, candidate.component_id, demoProject.lot_id)
    if (detail.disposition_history.length === 0) {
      freshComponent = candidate
      break
    }
  }
  console.log(`Complete lot: ${demoProject.lot_id} (flagged part: ${freshComponent.component_id})`)
  console.log(`In-progress lot: ${inProgressProject.lot_id}`)

  console.log(`Starting vite dev on port ${VITE_PORT}...`)
  const vite: ChildProcessWithoutNullStreams = spawn(
    'npx',
    ['vite', '--port', String(VITE_PORT), '--strictPort'],
    {
      cwd: FRONTEND_ROOT,
      env: { ...process.env, VITE_API_BASE_URL: API_BASE_URL },
      shell: true,
    },
  )
  vite.stdout.on('data', (d) => process.stdout.write(`[vite] ${d}`))
  vite.stderr.on('data', (d) => process.stderr.write(`[vite] ${d}`))

  try {
    await waitForServer(APP_URL)
    console.log('vite dev ready.')

    const browser = await chromium.launch()
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

    // Every console error / uncaught page error of every screen, tagged with the screen it came from.
    let currentScreen = 'startup'
    const consoleErrors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(`[${currentScreen}] console.error: ${msg.text()}`)
    })
    page.on('pageerror', (err) => consoleErrors.push(`[${currentScreen}] pageerror: ${err.message}`))

    async function signIn(accountId: string, displayName: string, pin: string) {
      await page.goto(`${APP_URL}/#/login`)
      await page.waitForSelector('text=Sign In')
      await page.getByLabel(displayName).check()
      await page.getByLabel('PIN').fill(pin)
      await page.getByRole('button', { name: /^sign in$/i }).click()
      await page.waitForURL((url) => !url.hash.includes('/login'))
      console.log(`  signed in as ${accountId}`)
    }

    async function signOut() {
      await page.getByRole('button', { name: 'Account menu' }).click()
      await page.getByRole('button', { name: 'Sign out' }).click()
      await page.waitForSelector('text=Sign In')
    }

    async function shot(name: string) {
      await page.waitForTimeout(400) // let charts/animations settle
      await page.screenshot({ path: path.join(SCREENSHOT_DIR, `${name}.png`) })
      console.log(`  captured ${name}.png`)
    }

    // 01: Login
    currentScreen = '01-login'
    await page.goto(`${APP_URL}/#/login`)
    await page.waitForSelector('text=Sign In')
    await shot('01-login')

    await signIn('a.sharma', 'A. Sharma', '1234')

    // Hard refresh: the token lives in memory only (rule 13), so a reload must land on Login.
    currentScreen = 'hard-refresh'
    await page.reload()
    await page.waitForSelector('text=Sign In')
    const afterReload = page.url()
    const tokenPersisted = await page.evaluate(
      () =>
        JSON.stringify({ ...localStorage }).toLowerCase().includes('token') ||
        JSON.stringify({ ...sessionStorage }).toLowerCase().includes('token') ||
        document.cookie.toLowerCase().includes('token'),
    )
    if (!/#\/login/.test(afterReload) || tokenPersisted) {
      throw new Error(`hard refresh check FAILED: url=${afterReload} tokenPersisted=${tokenPersisted}`)
    }
    console.log(`Hard refresh check: PASS - reload landed on ${afterReload}, no token in storage/cookies`)

    await signIn('a.sharma', 'A. Sharma', '1234')

    // 02: Ingest
    currentScreen = '02 Ingest'
    await page.waitForLoadState('networkidle')
    await shot('02-ingest')

    // 03: Project Browser
    currentScreen = '03 Project Browser'
    await page.goto(`${APP_URL}/#/projects`)
    await page.waitForLoadState('networkidle')
    await shot('03-project-browser')

    // 04: Lot Dashboard, Complete lot, with a DPA work order generated
    currentScreen = '04 Lot Dashboard'
    await page.goto(`${APP_URL}/#/lots/${encodeURIComponent(demoProject.lot_id)}`)
    await page.waitForSelector('text=/PDA:/')
    const dpaButton = page.getByRole('button', { name: /generate dpa work order/i })
    if (await dpaButton.isVisible()) {
      await dpaButton.click()
      await page.waitForSelector('text=DPA Work Order')
    }
    await shot('04-lot-dashboard-complete')

    // 05: Lot Dashboard, in-progress lot
    currentScreen = '05 Lot Dashboard'
    await page.goto(`${APP_URL}/#/lots/${encodeURIComponent(inProgressProject.lot_id)}`)
    await page.waitForSelector('text=/PDA:/')
    await shot('05-lot-dashboard-in-progress')

    // 06: Part Detail, flagged part on the Complete lot
    currentScreen = '06 Part Detail'
    await page.goto(`${APP_URL}/#/parts/${encodeURIComponent(freshComponent.component_id)}`)
    await page.waitForSelector('h1.screen-title')
    await shot('06-part-detail-flagged-complete')

    // 07: Part Detail, a part on the in-progress lot (module_a null)
    currentScreen = '07 Part Detail'
    await page.goto(`${APP_URL}/#/parts/c1`)
    await page.waitForSelector('h1.screen-title')
    await shot('07-part-detail-in-progress')

    // 08: History
    currentScreen = '08 History'
    await page.goto(`${APP_URL}/#/history`)
    await page.waitForLoadState('networkidle')
    await shot('08-history')

    // 09: Settings, with worklist and corrective status loaded
    currentScreen = '09 Settings'
    await page.goto(`${APP_URL}/#/settings`)
    await page.waitForSelector('text=Corrective Feedback Status')
    await page.waitForSelector('text=Worklist')
    await shot('09-settings')

    // 10-11: the fresh flagged part, first sign-off as a.sharma, second as r.mehta.
    currentScreen = '10-11 the fresh flagged part'
    const freshPath = `${APP_URL}/#/parts/${encodeURIComponent(freshComponent.component_id)}`
    await page.goto(freshPath)
    await page.waitForSelector('h1.screen-title')
    await page.getByLabel(/Technical Disposition Rationale/).fill('Leakage drift confirmed at 24h.')
    await page.getByRole('button', { name: 'Reject', exact: true }).click()
    await page.waitForSelector('text=/1 sign-off.s. recorded by distinct accounts/')
    await shot('10-part-detail-after-first-signoff')

    await signOut()
    await signIn('r.mehta', 'R. Mehta', '5678')
    await page.goto(freshPath)
    await page.waitForSelector('h1.screen-title')
    await page.getByLabel(/Technical Disposition Rationale/).fill('Concur: reject.')
    await page.getByRole('button', { name: 'Reject', exact: true }).click()
    await page.waitForSelector('text=/2 sign-off.s. recorded by distinct accounts/')
    await shot('11-part-detail-after-second-signoff')

    // 12: History with the timing_flag row (two sign-offs < 2 minutes apart).
    currentScreen = '12 History with the timing_flag row (two sign-of'
    await page.goto(`${APP_URL}/#/history`)
    await page.waitForLoadState('networkidle')
    await page.waitForSelector('text=/Sign-offs occurred/')
    await shot('12-history-with-timing-flag')

    // 13-14: error states - abort the screen's own API request and screenshot the visible message.
    currentScreen = '13-14 error states'
    currentScreen = '13-lot-dashboard-error-state (request aborted on purpose)'
    const lotPattern = `**/lots/${encodeURIComponent(demoProject.lot_id)}`
    await page.route(lotPattern, (route) => route.abort())
    await page.goto(`${APP_URL}/#/lots/${encodeURIComponent(demoProject.lot_id)}`)
    await page.waitForSelector('[role=alert]', { timeout: 45000 })
    await shot('13-lot-dashboard-error-state')
    await page.unroute(lotPattern)

    currentScreen = '14-part-detail-error-state (request aborted on purpose)'
    const partPattern = `**/parts/${encodeURIComponent(freshComponent.component_id)}*`
    await page.route(partPattern, (route) => route.abort())
    await page.goto(freshPath)
    await page.waitForSelector('[role=alert]', { timeout: 45000 })
    await shot('14-part-detail-error-state')
    await page.unroute(partPattern)

    await browser.close()
    await writeFile(
      path.join(SCREENSHOT_DIR, 'console-errors.txt'),
      consoleErrors.length > 0
        ? consoleErrors.join('\n') + '\n'
        : 'No console errors or uncaught page errors on any screen.\n',
    )
    console.log(`Console errors recorded: ${consoleErrors.length}`)
    console.log('\nAll screenshots captured.')
  } finally {
    // `vite.kill()` alone only kills the shell wrapper on Windows (spawned with shell: true),
    // leaving the real vite process holding the port - taskkill /T kills the whole process tree.
    if (vite.pid) {
      try {
        execFileSync('taskkill', ['/F', '/T', '/PID', String(vite.pid)])
      } catch {
        vite.kill()
      }
    }
  }
}

main().catch((error) => {
  console.error('\n' + (error instanceof Error ? error.message : String(error)))
  process.exitCode = 1
})
