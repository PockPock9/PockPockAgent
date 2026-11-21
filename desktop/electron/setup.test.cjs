const test = require('node:test')
const assert = require('node:assert/strict')
const { Setup } = require('./setup.cjs')

// Issues #51 and #85: one failed download (the agent browser or a model) should not fail setup.
function fakeSetup(results) {
  const calls = []
  const logs = []
  return {
    calls,
    logs,
    cancelled: false,
    log: (line) => logs.push(line),
    must: async (...args) => { calls.push(args); const next = results.shift(); if (next instanceof Error) throw next; return next },
    pull: async (model) => { calls.push(model); const next = results.shift(); if (next instanceof Error) throw next; return next },
  }
}

test('the agent browser download is tried again after a failure', async () => {
  const setup = fakeSetup([new Error('Installing the agent browser failed (exit code 1).'), { code: 0 }])
  const result = await Setup.prototype.mustRetry.call(setup, 'python', ['-m', 'playwright', 'install', 'chromium'], 'Installing the agent browser', {}, { delayMs: 1 })
  assert.deepEqual(result, { code: 0 })
  assert.equal(setup.calls.length, 2)
  assert.match(setup.logs[0], /attempt 1 of 3/)
})

test('the browser download gives up after three failures or a cancel', async () => {
  const failing = fakeSetup([new Error('a'), new Error('b'), new Error('c')])
  await assert.rejects(Setup.prototype.mustRetry.call(failing, 'python', [], 'Installing', {}, { delayMs: 1 }), /c/)
  assert.equal(failing.calls.length, 3)
  const cancelled = fakeSetup([new Error('stopped')])
  cancelled.cancelled = true
  await assert.rejects(Setup.prototype.mustRetry.call(cancelled, 'python', [], 'Installing', {}, { delayMs: 1 }), /stopped/)
  assert.equal(cancelled.calls.length, 1)
})

test('a model download is retried, but an unknown model is not', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const flaky = fakeSetup([new Error('Downloading qwen3.5:2b failed: context deadline exceeded'), undefined])
  const pending = Setup.prototype.pullWithRetry.call(flaky, 'qwen3.5:2b', () => undefined)
  await new Promise((resolve) => setImmediate(resolve))
  t.mock.timers.tick(5000)
  await pending
  assert.deepEqual(flaky.calls, ['qwen3.5:2b', 'qwen3.5:2b'])
  const unknown = fakeSetup([new Error('Downloading qwen3.5:1.5b failed: file does not exist')])
  await assert.rejects(Setup.prototype.pullWithRetry.call(unknown, 'qwen3.5:1.5b', () => undefined), /does not exist/)
  assert.equal(unknown.calls.length, 1)
})
