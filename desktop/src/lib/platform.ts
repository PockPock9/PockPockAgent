// What the renderer needs to know about the operating system, read synchronously from the user agent
// (the sandboxed page has no access to Node's process object).
export const isMac = /Macintosh|Mac OS X/.test(navigator.userAgent)

/** Prefix for keyboard shortcut labels: "⌘" on macOS, "Ctrl+" elsewhere. */
export const mod = isMac ? '⌘' : 'Ctrl+'

/** The primary shortcut modifier: Command on macOS, Control elsewhere. */
export const hasMod = (event: KeyboardEvent) => (isMac ? event.metaKey && !event.ctrlKey : event.ctrlKey)

/** How to refer to this computer in the interface. */
export const computer = isMac ? 'Mac' : 'PC'
