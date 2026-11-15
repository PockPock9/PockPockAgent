"use strict";

const NATIVE_HOST = "com.pockpock.chrome_companion";
const CONNECT_TIMEOUT_MS = 5000;

let nativePort = null;
let pendingPort = null;
let selectedTabId = null;
let selectedOrigin = null;
let selectedPairingId = null;
let pendingTabId = null;
let pendingOrigin = null;

function isPopupSender(sender) {
  return sender.id === chrome.runtime.id &&
    sender.url === chrome.runtime.getURL("popup.html");
}

function pageOrigin(url) {
  try {
    const parsed = new URL(url);
    if ((parsed.protocol !== "http:" && parsed.protocol !== "https:") ||
        parsed.username || parsed.password) {
      return null;
    }
    return parsed.origin;
  } catch {
    return null;
  }
}

function clearPort(port) {
  if (nativePort === port) {
    nativePort = null;
    selectedTabId = null;
    selectedOrigin = null;
    selectedPairingId = null;
  }
  if (pendingPort === port) {
    pendingPort = null;
    pendingTabId = null;
    pendingOrigin = null;
  }
}

function disconnectPort() {
  const port = nativePort || pendingPort;
  nativePort = null;
  pendingPort = null;
  selectedTabId = null;
  selectedOrigin = null;
  selectedPairingId = null;
  pendingTabId = null;
  pendingOrigin = null;
  if (port) {
    port.disconnect();
  }
}

function isHexId(value) {
  return typeof value === "string" && /^[a-f0-9]{32}$/.test(value);
}

async function handleRelayCommand(port, message) {
  if (nativePort !== port ||
      message.pairingId !== selectedPairingId ||
      message.tabId !== selectedTabId ||
      message.origin !== selectedOrigin ||
      !isHexId(message.requestId) ||
      !isHexId(message.runId)) {
    return;
  }

  let result;
  if (message.operation !== "ping" ||
      !message.payload ||
      typeof message.payload !== "object" ||
      Array.isArray(message.payload) ||
      Object.keys(message.payload).length !== 0) {
    result = {
      error: {
        code: "unsupported_operation",
        message: "The Chrome companion operation is not available."
      }
    };
  } else {
    try {
      const currentTab = await chrome.tabs.get(selectedTabId);
      if (pageOrigin(currentTab.url) !== selectedOrigin || nativePort !== port) {
        disconnectPort();
        return;
      }
      result = { ok: true, operation: "ping" };
    } catch {
      disconnectPort();
      return;
    }
  }

  port.postMessage({
    type: "result",
    pairingId: selectedPairingId,
    requestId: message.requestId,
    tabId: selectedTabId,
    origin: selectedOrigin,
    result
  });
}

async function connectActiveTab(sendResponse) {
  if (nativePort || pendingPort) {
    sendResponse({ ok: false, error: "A tab is already connected." });
    return;
  }

  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const tab = tabs[0];
    if (!tab || !Number.isInteger(tab.id) || typeof tab.url !== "string") {
      sendResponse({ ok: false, error: "The active tab is unavailable." });
      return;
    }

    const origin = pageOrigin(tab.url);
    if (!origin) {
      sendResponse({ ok: false, error: "Only HTTP and HTTPS tabs can be paired." });
      return;
    }

    pendingTabId = tab.id;
    pendingOrigin = origin;
    const port = chrome.runtime.connectNative(NATIVE_HOST);
    pendingPort = port;
    let completed = false;
    const finish = (result) => {
      if (completed) {
        return;
      }
      completed = true;
      clearTimeout(timeout);
      sendResponse(result);
    };
    const timeout = setTimeout(() => {
      clearPort(port);
      port.disconnect();
      finish({ ok: false, error: "The Native Messaging host did not respond." });
    }, CONNECT_TIMEOUT_MS);

    port.onMessage.addListener((message) => {
      if (pendingPort === port && message && message.type === "connected" &&
          message.tabId === tab.id && message.origin === origin) {
        if (!isHexId(message.pairingId)) {
          clearPort(port);
          port.disconnect();
          finish({ ok: false, error: "The local Chrome relay returned an invalid pairing." });
          return;
        }
        void chrome.tabs.get(tab.id).then((currentTab) => {
          if (pendingPort !== port) {
            return;
          }
          if (pageOrigin(currentTab.url) !== origin) {
            clearPort(port);
            port.disconnect();
            finish({ ok: false, error: "The active tab changed origin during pairing." });
            return;
          }
          pendingPort = null;
          pendingTabId = null;
          pendingOrigin = null;
          nativePort = port;
          selectedTabId = tab.id;
          selectedOrigin = origin;
          selectedPairingId = message.pairingId;
          finish({ ok: true, connected: true, origin });
        }).catch(() => {
          clearPort(port);
          port.disconnect();
          finish({ ok: false, error: "The selected tab closed during pairing." });
        });
        return;
      }
      if (message && message.type === "error" &&
          (nativePort === port || pendingPort === port)) {
        clearPort(port);
        port.disconnect();
        finish({ ok: false, error: "The local Chrome relay disconnected." });
        return;
      }
      if (nativePort === port && message && message.type === "command") {
        void handleRelayCommand(port, message);
        return;
      }
      if (nativePort !== port && pendingPort !== port) {
        return;
      }
      clearPort(port);
      port.disconnect();
      finish({ ok: false, error: "The Native Messaging host rejected the connection." });
    });

    port.onDisconnect.addListener(() => {
      const error = chrome.runtime.lastError;
      clearPort(port);
      finish({
        ok: false,
        error: error && error.message
          ? "Native Messaging failed: " + error.message
          : "The Native Messaging connection closed."
      });
    });

    port.postMessage({ type: "connect", tabId: tab.id, origin });
  } catch (error) {
    if (pendingPort) {
      disconnectPort();
    } else {
      pendingTabId = null;
      pendingOrigin = null;
    }
    sendResponse({
      ok: false,
      error: error instanceof Error ? error.message : "Could not connect to the Native Messaging host."
    });
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!isPopupSender(sender) || !message || typeof message.type !== "string") {
    return false;
  }

  if (message.type === "status") {
    sendResponse({
      connected: Boolean(nativePort),
      origin: nativePort ? selectedOrigin : null
    });
    return false;
  }

  if (message.type === "connect") {
    void connectActiveTab(sendResponse);
    return true;
  }

  if (message.type === "disconnect") {
    disconnectPort();
    sendResponse({ ok: true, connected: false });
    return false;
  }

  return false;
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  const expectedOrigin = tabId === selectedTabId
    ? selectedOrigin
    : tabId === pendingTabId ? pendingOrigin : null;
  if (!expectedOrigin || typeof changeInfo.url !== "string") {
    return;
  }
  if (pageOrigin(changeInfo.url) !== expectedOrigin) {
    disconnectPort();
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === selectedTabId || tabId === pendingTabId) {
    disconnectPort();
  }
});
