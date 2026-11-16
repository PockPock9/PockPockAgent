// Themes: the list shown in the picker, applying the saved choice, and the terminal colours.
// The colours themselves are CSS custom properties in styles.css (:root and [data-theme="…"]).
// The first paint is handled by public/theme-boot.js; this takes over once settings have loaded.
import { useEffect } from 'react'
import { bridge } from './types'

export type ThemeId = 'pockpock-dark' | 'volt' | 'storm' | 'feather' | 'system'
type ConcreteTheme = Exclude<ThemeId, 'system'>

/** Picker entries. Swatches are literal colours (canvas, side panel, accent, text) because they
 * preview themes that are not active; keep them equal to the tokens in styles.css. */
export const THEMES: Array<{ id: ThemeId; name: string; detail: string; swatches: string[] }> = [
  { id: 'pockpock-dark', name: 'PockPock Dark', detail: 'The default. Dark, with a violet accent.', swatches: ['#0d1014', '#171c24', '#8b6cff', '#e6ebf1'] },
  { id: 'volt', name: 'Volt', detail: 'Ink surfaces with the brand’s volt yellow.', swatches: ['#14111c', '#231d33', '#ffd60a', '#fff4d6'] },
  { id: 'storm', name: 'Storm', detail: 'Ink surfaces with the brand’s storm violet.', swatches: ['#14111c', '#231d33', '#5b4bf0', '#f4f1ff'] },
  { id: 'feather', name: 'Feather', detail: 'Light. Warm white with ink text.', swatches: ['#fffaf0', '#f7efdf', '#5b4bf0', '#14111c'] },
  { id: 'system', name: 'System', detail: 'Feather or PockPock Dark, following your computer’s light or dark mode.', swatches: ['#fffaf0', '#5b4bf0', '#0d1014', '#8b6cff'] },
]

export const THEME_IDS = THEMES.map((theme) => theme.id)

export function validTheme(id: unknown): ThemeId {
  return THEME_IDS.includes(id as ThemeId) ? (id as ThemeId) : 'pockpock-dark'
}

export function resolveTheme(id: ThemeId): ConcreteTheme {
  if (id !== 'system') return id
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'feather' : 'pockpock-dark'
}

/** Fired on window after data-theme changes, for code that reads tokens in JavaScript (the terminal). */
export const THEME_EVENT = 'pockpock:theme'

/** Applies the saved theme, and with "system" follows the operating system while the app runs. */
export function useTheme(setting: unknown, loaded: boolean) {
  useEffect(() => {
    if (!loaded) return // keep what theme-boot.js applied until the saved setting is known
    const id = validTheme(setting)
    const apply = () => {
      const next = resolveTheme(id)
      if (document.documentElement.dataset.theme !== next) {
        document.documentElement.dataset.theme = next
        window.dispatchEvent(new Event(THEME_EVENT))
      }
    }
    apply()
    // The main process sets Chromium's colour scheme (needed before "system" can read the OS
    // setting) and the window chrome; apply again once it has.
    void bridge()?.theme.set(id).then(apply, apply)
    if (id !== 'system') return
    const media = window.matchMedia('(prefers-color-scheme: light)')
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [setting, loaded])
}

/** ANSI colours for the terminal. xterm's defaults put red, blue and magenta below 4.5:1 on dark
 * backgrounds, and yellow and white are unreadable on light ones. Every text colour here is at least
 * 5.5:1 on its themes' terminal background (black is a background colour in practice). */
const ANSI_DARK = {
  black: '#3b3f4a', red: '#ff6b6b', green: '#4cc38a', yellow: '#ffd166', blue: '#6ea8ff', magenta: '#d38cff', cyan: '#4fd1d9', white: '#d6dde6',
  brightBlack: '#8a91a0', brightRed: '#ff8f8f', brightGreen: '#7fdcb8', brightYellow: '#ffe08a', brightBlue: '#94bfff', brightMagenta: '#e2adff', brightCyan: '#7fe3e9', brightWhite: '#ffffff',
}
const ANSI_LIGHT = {
  black: '#14111c', red: '#ad2219', green: '#136443', yellow: '#7f4a00', blue: '#2b4bc7', magenta: '#7e2fb8', cyan: '#0b6070', white: '#5f576b',
  brightBlack: '#5f576b', brightRed: '#c22a20', brightGreen: '#16734d', brightYellow: '#8a5300', brightBlue: '#3550d4', brightMagenta: '#8b35c9', brightCyan: '#0d6b7d', brightWhite: '#14111c',
}

/** xterm colours from the active theme's tokens, with the matching ANSI palette. */
export function terminalTheme() {
  const style = getComputedStyle(document.documentElement)
  const token = (name: string) => style.getPropertyValue(name).trim()
  const light = document.documentElement.dataset.theme === 'feather'
  return {
    background: token('--term-bg'), foreground: token('--term-fg'), cursor: token('--term-cursor'), cursorAccent: token('--term-bg'), selectionBackground: token('--term-selection'),
    ...(light ? ANSI_LIGHT : ANSI_DARK),
  }
}
