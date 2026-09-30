/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend location; rules in resolveApiBaseUrl (src/api/client.ts) and .env.example. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
