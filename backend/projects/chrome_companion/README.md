# PockPock Chrome Companion

This Windows-only development slice pairs one active Chrome tab with its exact HTTP(S) origin and relays bounded, transient requests through the local gateway. The relay currently supports only a `ping`; it does not read page content, click/type, access Chrome profiles, or expose an agent tool yet.

## Install for local development

1. In Chrome Stable, open `chrome://extensions` and enable **Developer mode**.
2. Select **Load unpacked** and choose this module's `extension` directory.
3. Copy the extension ID shown by Chrome.
4. Start the PockPock local gateway.
5. From Windows PowerShell, run this script from the repository:

   ```powershell
   .\backend\projects\chrome_companion\install.ps1 -ExtensionId '<32-character-extension-id>'
   ```

   The script compiles the small Native Messaging host using the Windows PowerShell/.NET Framework compiler, stores it under `%LOCALAPPDATA%\FrogAI\chrome-companion`, and registers its manifest for the current Windows user. It does not require administrator rights.
6. Reload the extension from `chrome://extensions`.
7. Select a normal HTTP(S) tab, open the extension popup, and choose **Connect active tab**. The popup displays the paired origin; **Disconnect** revokes the connection. Closing the tab or navigating to another origin also disconnects it.

Keep the unpacked extension at the same path after registering its ID. To remove the development installation, remove the extension in Chrome and delete the `com.pockpock.chrome_companion` value under `HKCU\Software\Google\Chrome\NativeMessagingHosts`, then remove `%LOCALAPPDATA%\FrogAI\chrome-companion`.

## Boundary and verification

The extension requests only `activeTab` and `nativeMessaging`; it has no persistent site access, `tabs` permission, content script, or `debugger` permission. Pairing is initiated from the toolbar popup. The service worker keeps the selected tab ID, exact origin, and pairing ID in memory only. The Native Messaging host validates Chrome's caller extension ID, uses the per-install service token for loopback gateway routes, and relays bounded messages. Relay state and run ownership are memory-only; one run owns the paired tab at a time. Navigation to another origin, tab closure, host failure, timeout, or explicit disconnect clears or fails the connection. The host does not receive or return page content or credentials.

Run the portable contract tests from `backend`:

```powershell
..\.venv\Scripts\python.exe -m unittest projects.chrome_companion.test_relay projects.chrome_companion.test_extension_contract
node --test projects\chrome_companion\extension\service_worker.test.js
```

End-to-end host registration and Chrome verification requires Chrome Stable and is not possible on machines where Chrome is absent. Agent-tool integration, observations/actions, approval binding, event replay, and cancellation remain follow-up work under AUT-02.
