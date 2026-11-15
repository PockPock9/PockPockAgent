// Theme ids the renderer may ask for, and the few colours the main process needs per theme: the
// window background shown before the page paints and the Windows title-bar overlay (caption
// buttons). Keep `bg` equal to --bg and `symbol` to --text-2 in desktop/src/styles.css.
const { nativeTheme } = require('electron')

const THEMES = {
  'pockpock-dark': { bg: '#0d1014', symbol: '#aeb8c6', dark: true },
  volt: { bg: '#14111c', symbol: '#ddd2b8', dark: true },
  storm: { bg: '#14111c', symbol: '#cdc6e6', dark: true },
  feather: { bg: '#fffaf0', symbol: '#433c4f', dark: false },
}
const IDS = [...Object.keys(THEMES), 'system']
const DEFAULT = 'pockpock-dark'

function valid(id) {
  return typeof id === 'string' && IDS.includes(id) ? id : DEFAULT
}

/** The concrete theme for a setting: "system" follows the operating system's light or dark mode. */
function resolve(id) {
  const theme = valid(id)
  if (theme !== 'system') return theme
  return nativeTheme.shouldUseDarkColors ? 'pockpock-dark' : 'feather'
}

/** Tells Chromium which colour scheme to report: the chosen one, or the OS setting for "system". */
function applyNative(id) {
  const theme = valid(id)
  nativeTheme.themeSource = theme === 'system' ? 'system' : THEMES[theme].dark ? 'dark' : 'light'
}

module.exports = { THEMES, IDS, DEFAULT, valid, resolve, applyNative }
