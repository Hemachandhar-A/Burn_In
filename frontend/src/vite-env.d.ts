/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin. Unset -> http://localhost:8000; empty string -> same-origin (demo build). */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
