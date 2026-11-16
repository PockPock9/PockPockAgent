// Maintenance Manager fix runs (LRN-04B) and their approval (LRN-04C).
//
// A run takes one report and: updates the PockPock copy from GitHub, creates a git worktree on a new
// `fix/report-<id>` branch from the latest main, lets the chosen AI edit that worktree, then checks the
// result itself (a documentation change is required; the project's own checks must pass for what
// changed). Nothing is committed or pushed until the user approves; approval commits, pushes and
// opens a *draft* pull request. Discarding removes the worktree and branch.
const fs = require('node:fs')
const path = require('node:path')
const { spawn } = require('node:child_process')
const paths = require('./paths.cjs')
const { redactText } = require('./reports.cjs')
const { runPockPockAgent } = require('./maintenance-agent.cjs')

const AGENT_TIMEOUT_MS = 45 * 60 * 1000
// OpenClaw counts every finished model call as progress, so a small model can "think" in circles for
// half an hour without touching a file. Real work means tool calls: stop after this long without one.
const OPENCLAW_IDLE_MS = 10 * 60 * 1000
const CHECK_TIMEOUT_MS = 20 * 60 * 1000
const PR_FILE = '.pockpock-pr.md'
const MAX_DIFF = 200_000

const isDocPath = (file) => /^docs\//.test(file) || /(^|\/)README\.md$/i.test(file) || /\.md$/i.test(file)

/** Which checks to run for a set of changed files (repository-relative, forward slashes). */
function planChecks(changed) {
  const code = changed.filter((file) => !isDocPath(file))
  const checks = []
  if (code.some((file) => file.startsWith('desktop/'))) {
    checks.push({ name: 'Install desktop packages', cwd: 'desktop', npm: ['ci', '--no-audit', '--no-fund'] })
    checks.push({ name: 'Desktop typecheck', cwd: 'desktop', npm: ['run', 'typecheck'] })
    checks.push({ name: 'Desktop unit tests', cwd: 'desktop', npm: ['test'] })
    checks.push({ name: 'Desktop build', cwd: 'desktop', npm: ['run', 'build'] })
  }
  if (code.some((file) => file.startsWith('backend/') && file.endsWith('.py'))) checks.push({ name: 'Backend tests', cwd: '.', python: ['backend/scripts/run_tests.py'] })
  if (code.some((file) => file.startsWith('backend/projects/openclaw_bridge/'))) checks.push({ name: 'OpenClaw bridge tests', cwd: '.', node: ['--test', 'backend/projects/openclaw_bridge/turn_helpers.test.mjs'] })
  return checks
}

function reportText(report) {
  const c = report.capture || {}
  const lines = [
    `Category: ${report.category}`,
    `User's description: ${report.description || '(none)'}`,
    `PockPock Agent ${c.appVersion} on ${c.platform}; mode ${c.engine}${c.model ? `; model ${c.model}` : ''}`,
    '',
    'The user asked:', c.userMessage || '(empty)',
  ]
  if (c.attachments?.length) lines.push(`Attached (names only): ${c.attachments.join(', ')}`)
  if (c.plan) lines.push('', `Plan (${c.plan.status}): ${c.plan.goal}`, ...c.plan.steps.map((step, index) => `  ${index + 1}. ${step}`))
  if (c.steps?.length) { lines.push('', 'Steps:'); for (const step of c.steps) lines.push(`  [${step.status}] ${step.label}${step.ms !== undefined ? ` (${(step.ms / 1000).toFixed(1)} s)` : ''}${step.detail ? ` — ${step.detail}` : ''}`) }
  if (c.approvals?.length) { lines.push('', 'Approvals:'); for (const item of c.approvals) lines.push(`  [${item.status}] ${item.title}: ${item.description}`) }
  lines.push('', `Reply (${c.status || 'unknown'}):`, c.reply || '(no reply)')
  if (c.notice) lines.push(`Notice: ${c.notice}`)
  if (c.timing?.length) lines.push(`Time: ${c.timing.map((phase) => `${phase.label} ${((phase.ms ?? 0) / 1000).toFixed(1)} s`).join(', ')}`)
  return lines.join('\n')
}

/** The instructions given to the coding agent. */
function buildPrompt(report) {
  return [
    'You are the coding agent of the PockPock Maintenance Manager. The current directory is a git worktree of the PockPock Agent repository on its own branch. Fix the problem a user reported (below).',
    '',
    'Rules:',
    '- Read AGENTS.md first and follow it.',
    '- Find the cause in the code and make the smallest correct fix. Do not refactor or reformat unrelated code.',
    '- Update the documentation in the same change, as AGENTS.md requires (the feature page in docs/features/, README.md and docs/ARCHITECTURE.md where they describe what changed). A fix without a documentation update is rejected.',
    '- Add or update a focused test where the changed code has tests.',
    '- Run the checks for what you changed: in desktop/ run `npm run typecheck`, `npm test` and `npm run build`; for Python changes run `python backend/scripts/run_tests.py`.',
    '- Do not commit, push, create branches or pull requests, or change git history. The Maintenance Manager commits after the user approves.',
    `- When done, write ${PR_FILE} in the repository root: the first line is "# " and a Conventional Commit title (for example "# fix(openclaw): retry browser calls with valid actions"), then a short description of what was wrong, the cause, the fix, the documentation you updated, and how you verified it. No personal details.`,
    `- If you cannot find or fix the cause, change no code and explain what you found in ${PR_FILE}.`,
    '',
    'The report (personal details were removed by the app):',
    '',
    reportText(report),
  ].join('\n')
}

/** Reads the title and body the agent wrote; falls back to a title from the report. */
function parsePrFile(text, report) {
  const trimmed = String(text || '').trim()
  const first = trimmed.split('\n')[0] || ''
  const title = first.replace(/^#\s*/, '').trim().slice(0, 120)
  const body = trimmed.split('\n').slice(1).join('\n').trim()
  const fallback = `fix: ${({ hang: 'reply hung', failed: 'reply failed', wrong: 'wrong result', other: 'reported problem' })[report.category] || 'reported problem'}${report.capture?.engine ? ` (${report.capture.engine})` : ''}`
  return { title: title || fallback, body }
}

// keepStdinOpen: gateway_turn.mjs treats a closed stdin as "the app went away" and aborts the turn,
// so the local agent's start request is written without closing stdin.
function spawnLogged(file, args, { cwd, input, timeout, onLine, onSpawn, shell = false, env, keepStdinOpen = false }) {
  return new Promise((resolve) => {
    let output = ''
    const child = spawn(file, args, { cwd, windowsHide: true, shell, env: env ?? paths.cleanEnv(), stdio: ['pipe', 'pipe', 'pipe'] })
    const timer = setTimeout(() => { child.kill(); onLine?.('Stopped: it ran out of time.') }, timeout)
    const onData = (chunk) => {
      const text = chunk.toString('utf8')
      output = (output + text).slice(-60_000)
      for (const line of text.split(/\r?\n/)) if (line.trim()) onLine?.(line.slice(0, 400))
    }
    child.stdout.on('data', onData)
    child.stderr.on('data', onData)
    child.on('error', (error) => { clearTimeout(timer); resolve({ ok: false, code: -1, output: `${output}\n${error.message}`, child }) })
    child.on('exit', (code) => { clearTimeout(timer); resolve({ ok: code === 0, code, output }) })
    onSpawn?.(child)
    if (keepStdinOpen) child.stdin.write(input ?? '')
    else if (input !== undefined) child.stdin.end(input)
    else child.stdin.end()
  })
}

/**
 * How to start a cloud agent's CLI. npm installs Claude Code and Codex as `.cmd` launchers, which
 * only run through cmd.exe, and Node does not escape arguments there. So the prompt (which carries
 * report text) goes in through stdin, never the command line, and the fixed arguments are quoted.
 * Copilot is a real .exe and takes the prompt as an argument without a shell.
 */
function agentCommand(id, file, prompt) {
  const shell = /\.(cmd|bat)$/i.test(file)
  const spec = {
    claude: { args: ['-p', '--permission-mode', 'acceptEdits', '--allowedTools', 'Read,Edit,Write,Glob,Grep,Bash(npm run *),Bash(npm test*),Bash(npm ci*),Bash(node *),Bash(python *),Bash(git diff*),Bash(git status*),Bash(git log*)'], input: prompt },
    codex: { args: ['exec', '--full-auto', '-'], input: prompt },
    copilot: shell ? null : { args: ['-p', prompt, '--allow-all-tools', '--deny-tool', 'shell(git push)', '--deny-tool', 'shell(git commit)', '--deny-tool', 'shell(gh)', '--deny-tool', 'shell(git reset)', '-s'] },
  }[id]
  if (!spec) throw new Error(`${id} cannot be started from ${path.basename(file || '')}.`)
  const quote = (value) => (/[\s()*&|<>^%!"]/.test(value) ? `"${value.replace(/"/g, '')}"` : value)
  return shell ? { file: quote(file), args: spec.args.map(quote), input: spec.input, shell } : { file, args: spec.args, input: spec.input, shell }
}

/** Calls onIdle once when touch() has not been called for idleMs. stop() ends the guard. */
function idleGuard(idleMs, onIdle, { now = Date.now, every = 15_000 } = {}) {
  let last = now()
  let fired = false
  const timer = setInterval(() => {
    if (!fired && now() - last >= idleMs) { fired = true; clearInterval(timer); onIdle() }
  }, every)
  timer.unref?.()
  return { touch: () => { last = now() }, stop: () => clearInterval(timer), get fired() { return fired } }
}

class FixRunner {
  constructor({ maintenance, reports, userData, emit }) {
    this.maintenance = maintenance
    this.reports = reports
    this.dir = path.join(userData, 'maintenance-runs')
    this.emit = emit
    this.active = new Map() // reportId -> child process
  }

  runFile(reportId) {
    this.reports.file(reportId) // validates the id
    return path.join(this.dir, `${reportId}.json`)
  }

  get(reportId) {
    try { return JSON.parse(fs.readFileSync(this.runFile(reportId), 'utf8')) } catch (error) { if (error.message === 'Unknown report.') throw error; return null }
  }

  save(run) {
    fs.mkdirSync(this.dir, { recursive: true })
    fs.writeFileSync(this.runFile(run.reportId), JSON.stringify(run, null, 2), 'utf8')
    this.emit({ type: 'fix', run })
    return run
  }

  log(run, line) {
    run.log = [...(run.log || []).slice(-400), line]
    this.emit({ type: 'fix-log', reportId: run.reportId, line })
  }

  async git(args, cwd) {
    return spawnLogged(this.maintenance.git(), args, { cwd, timeout: 10 * 60 * 1000 })
  }

  /** Starts a fix run; returns at once and reports progress through events. */
  async start(reportId) {
    const report = this.reports.get(reportId)
    const setup = await this.maintenance.status()
    if (!setup.ready) throw new Error('Set up the Maintenance Manager first.')
    if (this.active.has(reportId)) throw new Error('A fix for this report is already running.')
    const previous = this.get(reportId)
    if (previous?.state === 'proposed') throw new Error('This report already has a pull request.')
    const short = reportId.split('-').pop()
    const run = { reportId, state: 'running', agent: setup.agent, branch: `fix/report-${short}`, worktree: path.join(path.dirname(setup.repo.dir), 'PockPockAgent-fixes', `report-${short}`), startedAt: Date.now(), log: [], checks: [] }
    this.active.set(reportId, null)
    this.save(run)
    if (report.status === 'open') this.reports.update(reportId, { status: 'in-progress' })
    void this.execute(run, report, setup).catch((error) => { this.finish(run, 'failed', error.message || String(error)) })
    return run
  }

  finish(run, state, reason = '') {
    run.state = state
    run.reason = reason
    run.endedAt = Date.now()
    this.active.delete(run.reportId)
    this.save(run)
    setTimeout(() => void this.autoNext(), 2000)
  }

  /**
   * Automatic mode: when it is on and nothing is running, start on the oldest open report that has
   * no fix attempt yet. Reports whose fix failed are not retried automatically, so a problem the AI
   * cannot fix does not loop. Returns the report id started, or ''.
   */
  async autoNext() {
    try {
      if (this.active.size) return ''
      const setup = await this.maintenance.status()
      if (!setup.ready || !setup.auto) return ''
      const next = this.reports.list().filter((report) => report.status === 'open' && !this.get(report.id)).sort((a, b) => a.createdAt - b.createdAt)[0]
      if (!next) return ''
      await this.start(next.id)
      return next.id
    } catch {
      return ''
    }
  }

  async execute(run, report, setup) {
    const repo = setup.repo.dir
    const base = setup.repo.fork ? 'upstream' : 'origin'
    this.log(run, `Updating the copy of PockPock from GitHub (${base}/main)…`)
    let result = await this.git(['fetch', base, 'main'], repo)
    if (!result.ok) return this.finish(run, 'failed', `Could not update the copy from GitHub: ${result.output.trim().split('\n').pop()}`)
    // A previous attempt for the same report is replaced.
    if (fs.existsSync(run.worktree)) await this.git(['worktree', 'remove', '--force', run.worktree], repo)
    await this.git(['branch', '-D', run.branch], repo)
    fs.mkdirSync(path.dirname(run.worktree), { recursive: true })
    result = await this.git(['worktree', 'add', '-b', run.branch, run.worktree, `${base}/main`], repo)
    if (!result.ok) return this.finish(run, 'failed', `Could not create a working copy: ${result.output.trim().split('\n').pop()}`)
    this.log(run, `Working copy ready on branch ${run.branch}.`)

    const prompt = buildPrompt(report)
    this.log(run, `Asking ${run.agent.id === 'local' ? `the local model ${run.agent.model}` : run.agent.id} to find and fix the problem. This can take a while…`)
    const agentResult = await this.runAgent(run, prompt)
    if (this.cancelled?.has(run.reportId)) { this.cancelled.delete(run.reportId); return this.finish(run, 'cancelled', 'Stopped by you.') }
    this.log(run, agentResult.ok ? 'The AI finished.' : `The AI stopped with an error (exit code ${agentResult.code}).`)

    // What the AI wrote for the pull request, then what it changed.
    const prPath = path.join(run.worktree, PR_FILE)
    const prText = fs.existsSync(prPath) ? fs.readFileSync(prPath, 'utf8') : ''
    fs.rmSync(prPath, { force: true })
    const pr = parsePrFile(prText, report)
    run.title = redactText(pr.title).text
    run.body = redactText(pr.body).text
    await this.git(['add', '-A', '-N'], run.worktree) // so new files appear in the diff
    const status = await this.git(['status', '--porcelain'], run.worktree)
    run.changed = status.output.split(/\r?\n/).filter(Boolean).map((line) => line.slice(3).trim().replace(/^"|"$/g, '').replace(/\\/g, '/'))
    const diff = await this.git(['diff'], run.worktree)
    const diffText = diff.output.split('\n').filter((line) => !/^warning: /.test(line)).join('\n') // git's line-ending notices
    run.diff = diffText.length > MAX_DIFF ? `${diffText.slice(0, MAX_DIFF)}\n… (diff truncated)` : diffText
    run.docsChanged = run.changed.some(isDocPath)
    if (!run.changed.length) return this.finish(run, 'failed', run.body ? 'The AI did not change anything. Its notes are below.' : 'The AI did not change anything.')
    if (!run.docsChanged) return this.finish(run, 'failed', 'The fix has no documentation update, which every fix needs. Run it again, or choose another AI.')

    for (const check of planChecks(run.changed)) {
      this.log(run, `Check: ${check.name}…`)
      const outcome = await this.runCheck(check, run)
      run.checks.push({ name: check.name, ok: outcome.ok, output: outcome.output.slice(-4000) })
      this.save(run)
      if (!outcome.ok) return this.finish(run, 'failed', `${check.name} failed. The output is below.`)
    }
    if (!run.checks.length) this.log(run, 'Only documentation changed, so there are no code checks to run.')
    this.finish(run, 'ready', '')
  }

  /** Runs the chosen AI in the worktree. */
  async runAgent(run, prompt) {
    const onLine = (line) => this.log(run, line)
    const onSpawn = (child) => this.active.set(run.reportId, child)
    const cwd = run.worktree
    const id = run.agent.id
    if (id === 'local' && run.agent.openclaw) return this.runOpenClaw(run, prompt, onLine, onSpawn)
    if (id === 'local') {
      // PockPock itself: its own small tool loop on the local model (maintenance-agent.cjs).
      const controller = new AbortController()
      this.active.set(run.reportId, { pid: 0, abort: () => controller.abort() })
      return runPockPockAgent({ model: run.agent.model, worktree: cwd, prompt, prFile: path.join(cwd, PR_FILE), onLine, signal: controller.signal })
    }
    const files = { claude: 'claude', codex: 'codex', copilot: 'copilot' }
    const agents = await this.maintenance.agents()
    if (!agents.find((agent) => agent.id === id)?.installed) return { ok: false, code: -1, output: `${files[id]} is not installed.` }
    const command = agentCommand(id, this.maintenance.agentPath(id), prompt)
    return spawnLogged(command.file, command.args, { cwd, timeout: AGENT_TIMEOUT_MS, onLine, onSpawn, shell: command.shell, input: command.input })
  }

  /**
   * PockPock itself through OpenClaw: an OpenClaw turn with Full access on the local model, told to
   * work only in the worktree. It can run commands (build, tests, the app), unlike the file-only loop.
   * It is stopped after 10 minutes without a tool call (idleGuard), on top of gateway_turn.mjs's watchdog.
   */
  async runOpenClaw(run, prompt, onLine, onSpawn) {
    const entry = paths.openclawEntry()
    if (!entry) return { ok: false, code: -1, output: 'OpenClaw is not installed.' }
    const cwd = run.worktree
    const script = path.join(paths.backendRoot(), 'projects', 'openclaw_bridge', 'gateway_turn.mjs')
    const message = [
      `Work only in this folder, a separate working copy of PockPock: ${cwd}`,
      `Start every command with: Set-Location -LiteralPath '${cwd}';`,
      'Use absolute paths inside that folder for every file you read or change. You may run commands to build, test and try the fix (for example `npm.cmd ci`, `npm.cmd run typecheck`, `npm.cmd test`, `npm.cmd run build` in desktop, and Python tests); stop any program you start.',
      `When done, write the PR text to ${path.join(cwd, PR_FILE)} as described below.`,
      '',
      prompt,
    ].join('\n')
    const start = JSON.stringify({ type: 'start', agent: 'main', sessionId: `pockpock-maintenance-${run.reportId}-${Date.now().toString(36)}`, message, mode: 'full', model: run.agent.model, timeoutSeconds: AGENT_TIMEOUT_MS / 1000 })
    let child = null
    const guard = idleGuard(OPENCLAW_IDLE_MS, () => {
      onLine(`Stopped: OpenClaw made no tool call for ${OPENCLAW_IDLE_MS / 60_000} minutes, so it was going in circles.`)
      child?.kill()
    })
    const result = await spawnLogged(entry.node, [script], { cwd, input: `${start}\n`, timeout: AGENT_TIMEOUT_MS + 60_000, keepStdinOpen: true, onSpawn: (spawned) => { child = spawned; onSpawn?.(spawned) }, onLine: (line) => {
      try {
        const event = JSON.parse(line)
        if (event.type === 'tool') guard.touch()
        if (event.type === 'tool' && event.phase === 'start') onLine(`· ${event.title || event.name}`)
        else if (event.type === 'tool' && event.phase === 'end' && event.error) onLine(`  ${event.error}`)
        else if (event.type === 'error') onLine(`OpenClaw: ${event.message}`)
      } catch { /* not an event line */ }
    } })
    guard.stop()
    const failed = guard.fired || result.output.split('\n').some((line) => /"type":"error"/.test(line))
    return { ...result, ok: result.ok && !failed }
  }

  async runCheck(check, run) {
    const cwd = path.join(run.worktree, check.cwd)
    const onLine = (line) => this.log(run, `  ${line}`)
    const onSpawn = (child) => this.active.set(run.reportId, child)
    if (check.npm) {
      const npm = paths.npmCmd()
      return spawnLogged(npm, check.npm, { cwd, timeout: CHECK_TIMEOUT_MS, onLine, onSpawn, shell: /\.cmd$/i.test(npm) })
    }
    if (check.python) return spawnLogged(paths.venvPython(), check.python, { cwd, timeout: CHECK_TIMEOUT_MS, onLine, onSpawn })
    return spawnLogged(paths.nodeExe() || process.execPath, check.node, { cwd, timeout: CHECK_TIMEOUT_MS, onLine, onSpawn, env: { ...paths.cleanEnv(), ELECTRON_RUN_AS_NODE: '1' } })
  }

  cancel(reportId) {
    this.cancelled = this.cancelled || new Set()
    this.cancelled.add(reportId)
    const child = this.active.get(reportId)
    if (child?.abort) child.abort()
    else if (child?.pid) require('./platform.cjs').killTreeSync(child.pid)
    return true
  }

  /** LRN-04C: commit, push, and open a draft pull request. Only called after the user approves. */
  async approve(reportId, { title, body }) {
    const run = this.get(reportId)
    if (!run || run.state !== 'ready') throw new Error('There is no checked fix to approve.')
    const setup = await this.maintenance.status()
    const account = await this.maintenance.github()
    if (!account.loggedIn) throw new Error('Connect GitHub first.')
    const report = this.reports.get(reportId)
    const finalTitle = redactText(String(title || run.title).slice(0, 120)).text
    const finalBody = redactText([
      String(body ?? run.body).trim(),
      '',
      '---',
      `Reported in PockPock Agent ${report.capture?.appVersion || ''} (${report.category}${report.capture?.engine ? `, ${report.capture.engine}` : ''}). Fixed by the Maintenance Manager with ${run.agent.id === 'local' ? `the local model ${run.agent.model}` : run.agent.id}; checks run: ${run.checks.map((check) => `${check.name} ${check.ok ? 'passed' : 'failed'}`).join(', ') || 'documentation only'}.`,
      'Opened as a draft after the reporter approved it. The project owner decides whether to merge.',
    ].join('\n')).text
    let result = await this.git(['add', '-A'], run.worktree)
    result = await this.git(['commit', '-m', finalTitle, '-m', finalBody], run.worktree)
    if (!result.ok) throw new Error(`Commit failed: ${result.output.trim().split('\n').pop()}`)
    result = await this.git(['push', '-u', 'origin', run.branch], run.worktree)
    if (!result.ok) throw new Error(`Push failed: ${result.output.trim().split('\n').pop()}`)
    const head = setup.repo.fork ? `${account.login}:${run.branch}` : run.branch
    const gh = this.maintenance.gh()
    const pr = await spawnLogged(gh, ['pr', 'create', '--draft', '--repo', setup.repo.upstream, '--base', 'main', '--head', head, '--title', finalTitle, '--body-file', '-'], { cwd: run.worktree, input: finalBody, timeout: 120000 })
    const url = (pr.output.match(/https:\/\/github\.com\/\S+\/pull\/\d+/) || [])[0]
    if (!pr.ok || !url) throw new Error(`The pull request could not be opened: ${pr.output.trim().split('\n').pop()}`)
    run.state = 'proposed'
    run.prUrl = url
    run.title = finalTitle
    run.body = finalBody
    this.save(run)
    this.reports.update(reportId, { status: 'in-progress' })
    return run
  }

  /** Throws the fix away: removes the worktree and its branch. */
  async discard(reportId) {
    const run = this.get(reportId)
    if (!run) return true
    if (run.state === 'running') throw new Error('Stop the fix first.')
    const setup = await this.maintenance.status()
    if (setup.repo?.dir && run.state !== 'proposed') {
      if (fs.existsSync(run.worktree)) await this.git(['worktree', 'remove', '--force', run.worktree], setup.repo.dir)
      await this.git(['branch', '-D', run.branch], setup.repo.dir)
    }
    fs.rmSync(this.runFile(reportId), { force: true })
    this.emit({ type: 'fix', run: { reportId, state: 'none' } })
    return true
  }
}

module.exports = { FixRunner, planChecks, buildPrompt, parsePrFile, isDocPath, idleGuard, agentCommand }
