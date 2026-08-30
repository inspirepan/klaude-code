/**
 * klaude: the sliver of the node API the vitest suites touch. `tsconfig.json`
 * keeps `"types": []`, so @types/node would have to be pulled into every
 * compilation unit for one stylesheet read; this declares just that call.
 * Vite's `?raw` query is not an option here: vitest resolves `*.module.css`
 * through its CSS-modules proxy whatever query follows it.
 */
declare module 'node:fs' {
  export function readFileSync(path: URL | string, encoding: 'utf8'): string
}
