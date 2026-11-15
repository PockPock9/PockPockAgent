// Tests for the permission plugin's policy. Run: node backend/projects/openclaw_bridge/plugin/test_policy.mjs
//
// The plugin imports the OpenClaw plugin SDK, which only exists inside an OpenClaw install, so
// the test copies it next to a one-line SDK stub in a temporary folder and loads it from there.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'pockpock-policy-'))
const sdk = path.join(sandbox, 'node_modules', 'openclaw', 'plugin-sdk')
fs.mkdirSync(sdk, { recursive: true })
fs.writeFileSync(path.join(sandbox, 'node_modules', 'openclaw', 'package.json'), JSON.stringify({
  name: 'openclaw', type: 'module', exports: { './plugin-sdk/plugin-entry': './plugin-sdk/plugin-entry.js' },
}))
fs.writeFileSync(path.join(sdk, 'plugin-entry.js'), 'export const definePluginEntry = (entry) => entry\n')
fs.copyFileSync(path.join(here, 'pockpock-permissions.ts'), path.join(sandbox, 'pockpock-permissions.ts'))
const stateDir = path.join(sandbox, 'state')
fs.mkdirSync(path.join(stateDir, 'pockpock'), { recursive: true })
process.env.OPENCLAW_STATE_DIR = stateDir
const stateFile = path.join(stateDir, 'pockpock', 'permissions.json')

const plugin = await import(pathToFileURL(path.join(sandbox, 'pockpock-permissions.ts')).href)
const { isReadOnlyCommand } = plugin

const readOnly = [
  'Get-ChildItem', 'dir C:\\Users', 'ls -Force', 'Get-Content notes.txt', 'cat a.txt | Select-String foo',
  'git status', 'git log --oneline -5', 'git diff HEAD~1', 'hostname', 'whoami', 'Test-Path x',
  'ollama list', 'node --version', 'python -V', 'Get-Process | Sort-Object CPU | Select-Object -First 5',
  'where.exe git', 'npm ls', 'docker ps', 'HOSTNAME.EXE',
]
const notReadOnly = [
  '', 'Remove-Item x', 'rm -rf x', 'del x', 'Get-Content a > b', 'dir >> log.txt', 'echo hi > file',
  'git push', 'git commit -m x', 'git diff --output=patch.txt', 'git', 'npm install', 'pip install x',
  'Get-ChildItem; Remove-Item x', 'dir && del x', 'dir | Remove-Item', 'Get-ChildItem | ForEach-Object { Remove-Item $_ }',
  'Get-Content (Remove-Item x)', 'echo $(Remove-Item x)', 'cat `whoami`', 'iex "Remove-Item x"',
  'dir | Invoke-Expression', 'Start-Process calc', 'powershell -Command "Remove-Item x"', 'cmd /c del x',
  'python script.py', 'node app.js', 'curl http://example.com', 'Invoke-WebRequest http://example.com',
  'Set-Content a b', 'New-Item x', 'Copy-Item a b', 'Move-Item a b', 'dir\nRemove-Item x', 'dir & del x',
  'docker run x', 'ollama rm model', 'ipconfig /release', 'nvidia-smi -pm 1', 'wsl rm -rf /', `dir ${'a'.repeat(700)}`,
]
for (const command of readOnly) assert.equal(isReadOnlyCommand(command), true, `should be read-only: ${command}`)
for (const command of notReadOnly) assert.equal(isReadOnlyCommand(command), false, `should need approval: ${command.slice(0, 60)}`)

// Drive the registered before_tool_call hook the way OpenClaw does.
let hook
const methods = {}
plugin.default.register({
  on: (name, handler) => { if (name === 'before_tool_call') hook = handler },
  registerGatewayMethod: (name, handler) => { methods[name] = handler },
})
const key = 'agent:main:explicit:pockpock-abc'
const setMode = (mode) => fs.writeFileSync(stateFile, JSON.stringify({ version: 1, sessions: mode ? { [key]: mode } : {} }))
const decide = (toolName, params = {}, sessionKey = key) => hook({ toolName, params }, { sessionKey })
const asks = (result) => Boolean(result?.requireApproval)

// Sessions PockPock did not start are left to OpenClaw's own policy.
setMode('ask')
assert.equal(decide('exec', { command: 'Remove-Item x' }, 'agent:main:main'), undefined)

// ask: every action prompts; bookkeeping tools do not.
for (const [tool, params] of [['exec', { command: 'hostname' }], ['read', { path: 'a' }], ['ls', {}], ['write', { path: 'a' }], ['web_fetch', { url: 'https://example.com' }], ['browser', {}], ['some_future_tool', {}]]) {
  assert.equal(asks(decide(tool, params)), true, `ask mode should prompt for ${tool}`)
}
assert.equal(decide('session_status'), undefined)
for (const wrapper of ['tool_search', 'tool_describe', 'dispatch_action']) assert.equal(decide(wrapper, { id: 'openclaw:browser:browser' }), undefined)
assert.equal(asks(decide('browser', { action: 'snapshot' })), true)
assert.equal(decide('browser', { action: 'open', url: 'https://example.com' }).requireApproval.description, 'open https://example.com')
assert.deepEqual(decide('exec', { command: 'hostname' }).requireApproval.allowedDecisions, ['allow-once', 'deny'])
assert.equal(decide('exec', { command: 'hostname' }).requireApproval.description, 'hostname')

// Tools from connected MCP servers always ask, and the card names the server and the tool.
assert.equal(decide('files__read_file', { path: 'a' }).requireApproval.title, 'Use MCP tool: files › read_file')
assert.equal(decide('some_future_tool', {}).requireApproval.title, 'Use tool: some_future_tool')

// auto: local reads and read-only commands run; everything else prompts.
setMode('auto')
assert.equal(decide('read', { path: 'a' }), undefined)
assert.equal(decide('ls'), undefined)
assert.equal(decide('exec', { command: 'git status' }), undefined)
assert.equal(decide('process', { action: 'poll' }), undefined)
assert.equal(decide('browser', { action: 'snapshot' }), undefined)
assert.equal(decide('computer', { action: 'screenshot' }), undefined)
assert.equal(asks(decide('files__read_file', { path: 'a' })), true)
assert.equal(asks(decide('computer', { action: 'left_click', coordinate: [10, 20] })), true)
assert.equal(asks(decide('computer', { action: 'type', text: 'hello' })), true)
assert.equal(asks(decide('browser', { action: 'open', url: 'https://example.com' })), true)
assert.equal(asks(decide('browser', { action: 'act', kind: 'click', ref: 'e1' })), true)
for (const [tool, params] of [['exec', { command: 'Remove-Item x' }], ['write', { path: 'a' }], ['edit', { path: 'a' }], ['apply_patch', {}], ['web_fetch', { url: 'https://example.com' }], ['process', { action: 'kill' }], ['browser', {}], ['message', {}], ['some_future_tool', {}]]) {
  assert.equal(asks(decide(tool, params)), true, `auto mode should prompt for ${tool}`)
}

// full: nothing prompts.
setMode('full')
assert.equal(decide('exec', { command: 'Remove-Item x' }), undefined)
assert.equal(decide('write', { path: 'a' }), undefined)

// A missing record, an unknown mode, or an unreadable file all fall back to ask.
setMode(null)
assert.equal(asks(decide('read', { path: 'a' })), true)
fs.writeFileSync(stateFile, JSON.stringify({ sessions: { [key]: 'root' } }))
assert.equal(asks(decide('exec', { command: 'hostname' })), true)
fs.writeFileSync(stateFile, '{ not json')
assert.equal(asks(decide('exec', { command: 'hostname' })), true)
fs.rmSync(stateFile)
assert.equal(asks(decide('exec', { command: 'hostname' })), true)

// The question tool is blocked in every mode because PockPock cannot answer it.
setMode('full')
assert.equal(decide('ask_user').block, true)

// Long or multi-line details are flattened and clipped to the gateway's limit.
setMode('ask')
const long = decide('exec', { command: `echo ${'x'.repeat(900)}\nsecond line` }).requireApproval.description
assert.ok(long.length <= 500 && !long.includes('\n'))

assert.ok(methods['pockpock.permissions.status'])
fs.rmSync(sandbox, { recursive: true, force: true })
console.log(`policy tests passed (${readOnly.length + notReadOnly.length} commands classified)`)
