"use strict";

const statusElement = document.getElementById("status");
const connectButton = document.getElementById("connect");
const disconnectButton = document.getElementById("disconnect");

function render(state) {
  if (state.connected) {
    statusElement.textContent = "Connected to " + state.origin + ".";
    connectButton.hidden = true;
    disconnectButton.hidden = false;
    return;
  }
  statusElement.textContent = state.error || "No tab is connected.";
  connectButton.hidden = false;
  disconnectButton.hidden = true;
}

async function send(type) {
  try {
    const response = await chrome.runtime.sendMessage({ type });
    if (!response) {
      render({ connected: false, error: "The companion service did not respond." });
      return;
    }
    render(response);
  } catch (error) {
    render({
      connected: false,
      error: error instanceof Error ? error.message : "The companion service is unavailable."
    });
  }
}

connectButton.addEventListener("click", () => {
  connectButton.disabled = true;
  statusElement.textContent = "Connecting the active tab…";
  void send("connect").finally(() => {
    connectButton.disabled = false;
  });
});

disconnectButton.addEventListener("click", () => {
  void send("disconnect");
});

void send("status");
