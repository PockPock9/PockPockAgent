// Applies the theme before the app renders, so the window never flashes the wrong colours. The main
// process passes the saved theme as ?theme= (resolved: "system" is already light or dark). React's
// theme hook (src/lib/theme.ts) takes over once settings load. A separate file because the page's
// Content-Security-Policy allows no inline scripts.
(function () {
  var allowed = ['pockpock-dark', 'volt', 'storm', 'feather']
  var theme = new URLSearchParams(window.location.search).get('theme')
  if (allowed.indexOf(theme) === -1) theme = 'pockpock-dark'
  document.documentElement.dataset.theme = theme
})()
