"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "service_worker.js"), "utf8");
const extensionId = "abcdefghijklmnopabcdefghijklmnop";
const popupUrl = `chrome-extension://${extensionId}/popup.html`;
const pairingId = "a".repeat(32);

function createWorker(initialUrl = "https://example.com/start") {
  let onMessage;
  let onUpdated;
  let onRemoved;
  let currentTab = { id: 17, url: initialUrl };
  const sentToHost = [];
  const port = {
    disconnected: false,
    onMessage: { addListener(listener) { this.listener = listener; } },
    onDisconnect: { addListener(listener) { this.listener = listener; } },
    postMessage(message) { sentToHost.push(message); },
    disconnect() {
      this.disconnected = true;
      if (this.onDisconnect.listener) {
        this.onDisconnect.listener();
      }
    }
  };
  const chrome = {
    runtime: {
      id: extensionId,
      getURL: (file) => `chrome-extension://${extensionId}/${file}`,
      onMessage: { addListener(listener) { onMessage = listener; } },
      connectNative: () => port
    },
    tabs: {
      query: async () => [currentTab],
      get: async () => currentTab,
      onUpdated: { addListener(listener) { onUpdated = listener; } },
      onRemoved: { addListener(listener) { onRemoved = listener; } }
    }
  };

  vm.runInNewContext(source, {
    chrome,
    URL,
    Number,
    Error,
    setTimeout,
    clearTimeout
  });

  function request(type, senderUrl = popupUrl) {
    return new Promise((resolve) => {
      const keepChannelOpen = onMessage(
        { type },
        { id: extensionId, url: senderUrl },
        (value) => resolve(
          value === undefined ? undefined : JSON.parse(JSON.stringify(value))
        )
      );
      if (!keepChannelOpen) {
        resolve(undefined);
      }
    });
  }

  return {
    request,
    port,
    sentToHost,
    navigate(url) {
      currentTab = { id: 17, url };
      onUpdated(17, { url });
    },
    removeTab() {
      onRemoved(17);
    },
    sendHostMessage(message) {
      port.onMessage.listener(message);
    }
  };
}

async function pair(worker) {
  const responsePromise = worker.request("connect");
  await new Promise((resolve) => setImmediate(resolve));
  worker.sendHostMessage({
    type: "connected",
    tabId: 17,
    origin: "https://example.com",
    pairingId
  });
  return responsePromise;
}

test("pairs only the active tab and revokes on cross-origin navigation", async () => {
  const worker = createWorker();
  const responsePromise = worker.request("connect");
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(JSON.parse(JSON.stringify(worker.sentToHost)), [{
    type: "connect",
    tabId: 17,
    origin: "https://example.com"
  }]);

  worker.sendHostMessage({
    type: "connected",
    tabId: 17,
    origin: "https://example.com",
    pairingId
  });
  assert.deepEqual(await responsePromise, {
    ok: true,
    connected: true,
    origin: "https://example.com"
  });
  assert.equal((await worker.request("status")).connected, true);

  worker.navigate("https://other.example/page");
  assert.equal(worker.port.disconnected, true);
  assert.equal((await worker.request("status")).connected, false);
});

test("rejects non-web tabs and messages not sent by the popup", async () => {
  const worker = createWorker("chrome://settings/");
  assert.deepEqual(await worker.request("connect"), {
    ok: false,
    error: "Only HTTP and HTTPS tabs can be paired."
  });
  assert.equal(await worker.request("connect", "https://example.com/"), undefined);
  assert.deepEqual(worker.sentToHost, []);
});

test("revokes a pairing if the tab changes origin during the handshake", async () => {
  const worker = createWorker();
  const responsePromise = worker.request("connect");
  await new Promise((resolve) => setImmediate(resolve));
  worker.navigate("https://other.example/page");
  worker.sendHostMessage({
    type: "connected",
    tabId: 17,
    origin: "https://example.com",
    pairingId
  });

  const response = await responsePromise;
  assert.equal(response.ok, false);
  assert.match(response.error, /Native Messaging connection closed|changed origin/);
  assert.equal(worker.port.disconnected, true);
  assert.equal((await worker.request("status")).connected, false);
});

test("tab closure and native host failure revoke the pairing", async () => {
  const closedTabWorker = createWorker();
  assert.deepEqual(await pair(closedTabWorker), {
    ok: true,
    connected: true,
    origin: "https://example.com"
  });
  closedTabWorker.removeTab();
  assert.equal(closedTabWorker.port.disconnected, true);
  assert.equal((await closedTabWorker.request("status")).connected, false);

  const failedHostWorker = createWorker();
  assert.deepEqual(await pair(failedHostWorker), {
    ok: true,
    connected: true,
    origin: "https://example.com"
  });
  failedHostWorker.port.onDisconnect.listener();
  assert.equal((await failedHostWorker.request("status")).connected, false);
});

test("the user can explicitly disconnect the selected tab", async () => {
  const worker = createWorker();
  await pair(worker);

  assert.deepEqual(await worker.request("disconnect"), {
    ok: true,
    connected: false
  });
  assert.equal(worker.port.disconnected, true);
  assert.equal((await worker.request("status")).connected, false);
});

test("relays only a valid request for the paired tab and run", async () => {
  const worker = createWorker();
  await pair(worker);

  worker.sendHostMessage({
    type: "command",
    pairingId: "b".repeat(32),
    requestId: "c".repeat(32),
    runId: "d".repeat(32),
    tabId: 17,
    origin: "https://example.com",
    operation: "ping",
    payload: {}
  });
  assert.equal(worker.sentToHost.length, 1);

  worker.sendHostMessage({
    type: "command",
    pairingId,
    requestId: "c".repeat(32),
    runId: "d".repeat(32),
    tabId: 17,
    origin: "https://example.com",
    operation: "ping",
    payload: {}
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(JSON.parse(JSON.stringify(worker.sentToHost[1])), {
    type: "result",
    pairingId,
    requestId: "c".repeat(32),
    tabId: 17,
    origin: "https://example.com",
    result: { ok: true, operation: "ping" }
  });
});
