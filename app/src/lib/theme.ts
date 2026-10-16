import { useSyncExternalStore } from 'react'

export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'a-share-knowledge-theme'
const listeners = new Set<() => void>()
let currentTheme: Theme = 'light'
let initialized = false

const isTheme = (value: unknown): value is Theme => value === 'dark' || value === 'light'
const DARK_SCHEME = '(prefers-color-scheme: dark)'

function savedTheme(): Theme | null {
  try { const value = window.localStorage.getItem(STORAGE_KEY); return isTheme(value) ? value : null } catch { return null }
}

/** 没有明确选择时跟随系统；index.html 的启动脚本用同一规则，首屏不会先白后黑。 */
function systemTheme(): Theme {
  return typeof window !== 'undefined' && window.matchMedia?.(DARK_SCHEME).matches ? 'dark' : 'light'
}

function applyDocumentTheme() {
  if (typeof document === 'undefined') return
  document.documentElement.dataset.theme = currentTheme
  document.documentElement.style.colorScheme = currentTheme
}

function commitTheme(theme: Theme, persist: boolean): Theme {
  const changed = currentTheme !== theme
  currentTheme = theme
  applyDocumentTheme()
  if (persist && typeof window !== 'undefined') {
    try { window.localStorage.setItem(STORAGE_KEY, theme) } catch { /* The theme still works when storage is unavailable. */ }
  }
  if (changed) listeners.forEach(listener => listener())
  return currentTheme
}

/** Initialize once before React renders; lazy pages must never reset this store. */
export function initializeTheme(): Theme {
  if (initialized || typeof window === 'undefined') return currentTheme
  initialized = true
  currentTheme = savedTheme() ?? systemTheme()
  applyDocumentTheme()
  window.addEventListener('storage', event => {
    if (event.key === STORAGE_KEY || event.key === null) {
      commitTheme(isTheme(event.newValue) ? event.newValue : systemTheme(), false)
    }
  })
  // 只要读者还没亲手选过主题，系统切换明暗时页面跟着走；选过之后以选择为准。
  window.matchMedia?.(DARK_SCHEME).addEventListener?.('change', event => {
    if (!savedTheme()) commitTheme(event.matches ? 'dark' : 'light', false)
  })
  return currentTheme
}

export function getTheme(): Theme { return initializeTheme() }

export function setTheme(theme: Theme): Theme {
  initializeTheme()
  return commitTheme(theme, true)
}

export function toggleTheme(): Theme {
  return setTheme(getTheme() === 'light' ? 'dark' : 'light')
}

export function subscribeTheme(listener: () => void): () => void {
  initializeTheme()
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribeTheme, getTheme, () => 'light')
}

