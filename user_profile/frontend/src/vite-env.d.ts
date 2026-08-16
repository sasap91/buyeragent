/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_HOME_URL?: string
}

declare module '*.csv?raw' {
  const content: string
  export default content
}
