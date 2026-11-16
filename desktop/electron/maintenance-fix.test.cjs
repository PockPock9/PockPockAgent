const test = require('node:test')
const assert = require('node:assert/strict')
const { planChecks, buildPrompt, parsePrFile, isDocPath } = require('./maintenance-fix.cjs')

test('documentation paths are recognised', () => {
  for (const file of ['docs/features/x.md', 'README.md', 'desktop/README.md', 'design-system/pockpock-desktop.md']) assert.equal(isDocPath(file), true, file)
  for (const file of ['desktop/src/App.tsx', 'backend/scripts/run_tests.py', 'docs.json']) assert.equal(isDocPath(file), false, file)
})

test('checks follow what changed; documentation alone needs none', () => {
  assert.deepEqual(planChecks(['docs/features/x.md', 'README.md']), [])
  assert.deepEqual(planChecks(['desktop/src/App.tsx', 'docs/a.md']).map((check) => check.name), ['Install desktop packages', 'Desktop typecheck', 'Desktop unit tests', 'Desktop build'])
  assert.deepEqual(planChecks(['backend/projects/planner/app.py']).map((check) => check.name), ['Backend tests'])
  assert.deepEqual(planChecks(['backend/projects/openclaw_bridge/gateway_turn.mjs']).map((check) => check.name), ['OpenClaw bridge tests'])
})

test('the prompt carries the rules and the redacted report', () => {
  const prompt = buildPrompt({ category: 'failed', description: 'npm is blocked', capture: { appVersion: '0.2.0', platform: 'win32 x64', engine: 'openclaw', model: 'qwen3.5:9b', userMessage: 'Is puppeteer installed?', attachments: [], steps: [{ label: 'Exec npm list', status: 'failed', detail: 'scripts are disabled', ms: 2000 }], approvals: [], reply: 'Could not check', status: 'done', notice: '', timing: [] } })
  for (const rule of ['Read AGENTS.md', 'documentation', 'Do not commit, push', '.pockpock-pr.md']) assert.ok(prompt.includes(rule), rule)
  assert.ok(prompt.includes('[failed] Exec npm list (2.0 s) — scripts are disabled'))
  assert.ok(prompt.includes("User's description: npm is blocked"))
})

test('PR text comes from the file the AI wrote, with a fallback title', () => {
  assert.deepEqual(parsePrFile('# fix(openclaw): use npm.cmd\n\nnpm is blocked by the script policy.', { category: 'failed' }), { title: 'fix(openclaw): use npm.cmd', body: 'npm is blocked by the script policy.' })
  assert.equal(parsePrFile('', { category: 'hang', capture: { engine: 'openclaw' } }).title, 'fix: reply hung (openclaw)')
})
