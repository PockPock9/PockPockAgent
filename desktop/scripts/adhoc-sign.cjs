// electron-builder afterPack hook. Without an Apple Developer ID the macOS app is left unsigned, and
// Apple silicon Macs refuse to run unsigned code at all. An ad-hoc signature ("-") lets it run; the
// first launch still needs the user to allow it once (see README: "Installing on a Mac").
const { execFileSync } = require('node:child_process')
const path = require('node:path')

exports.default = async function adhocSign(context) {
  if (context.electronPlatformName !== 'darwin') return
  if (process.env.CSC_LINK || process.env.CSC_NAME) return // a real certificate signs it instead
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`)
  execFileSync('codesign', ['--force', '--deep', '--sign', '-', app], { stdio: 'inherit' })
}
