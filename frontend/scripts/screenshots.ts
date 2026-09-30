/**
 * Screenshot capture for Block 5C Part 4. Starts `vite dev` on its own port (not the app's
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
 */
import { chromium } from '@playwright/test'
import { execFileSync, spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { login } from '../src/api/auth'
import { createApiClient } from '../src/api/client'
import { getLotSummary } from '../src/api/lotDetail'
import { listProjects } from '../src/api/lots'

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

async function main() {
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
  console.log(`Complete lot: ${demoProject.lot_id} (flagged part: ${flaggedComponent.component_id})`)
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

    async function shot(name: string) {
      await page.waitForTimeout(400) // let charts/animations settle
      await page.screenshot({ path: path.join(SCREENSHOT_DIR, `${name}.png`) })
      console.log(`  captured ${name}.png`)
    }

    // 01: Login
    await page.goto(`${APP_URL}/#/login`)
    await page.waitForSelector('text=Sign In')
    await shot('01-login')

    // Sign in as a.sharma (already the default-selected account).
    await page.getByLabel('PIN').fill('1234')
    await page.getByRole('button', { name: /^sign in$/i }).click()
    await page.waitForURL(/#\/ingest/)

    // 02: Ingest
    await page.waitForLoadState('networkidle')
    await shot('02-ingest')

    // 03: Project Browser
    await page.goto(`${APP_URL}/#/projects`)
    await page.waitForLoadState('networkidle')
    await shot('03-project-browser')

    // 04: Lot Dashboard, Complete lot, with a DPA work order generated
    await page.goto(`${APP_URL}/#/lots/${encodeURIComponent(demoProject.lot_id)}`)
    await page.waitForSelector('text=/PDA:/')
    const dpaButton = page.getByRole('button', { name: /generate dpa work order/i })
    if (await dpaButton.isVisible()) {
      await dpaButton.click()
      await page.waitForSelector('text=DPA Work Order')
    }
    await shot('04-lot-dashboard-complete')

    // 05: Lot Dashboard, in-progress lot
    await page.goto(`${APP_URL}/#/lots/${encodeURIComponent(inProgressProject.lot_id)}`)
    await page.waitForSelector('text=/PDA:/')
    await shot('05-lot-dashboard-in-progress')

    // 06: Part Detail, flagged part on the Complete lot
    await page.goto(`${APP_URL}/#/parts/${encodeURIComponent(flaggedComponent.component_id)}`)
    await page.waitForSelector('h1.screen-title')
    await shot('06-part-detail-flagged-complete')

    // 07: Part Detail, a part on the in-progress lot (module_a null)
    await page.goto(`${APP_URL}/#/parts/c1`)
    await page.waitForSelector('h1.screen-title')
    await shot('07-part-detail-in-progress')

    // 08: History
    await page.goto(`${APP_URL}/#/history`)
    await page.waitForLoadState('networkidle')
    await shot('08-history')

    // 09: Settings, with worklist and corrective status loaded
    await page.goto(`${APP_URL}/#/settings`)
    await page.waitForSelector('text=Corrective Feedback Status')
    await page.waitForSelector('text=Worklist')
    await shot('09-settings')

    await browser.close()
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
