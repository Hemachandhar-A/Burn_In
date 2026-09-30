import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// RTL only auto-unmounts between tests when Vitest globals are on; they aren't here.
afterEach(cleanup)
