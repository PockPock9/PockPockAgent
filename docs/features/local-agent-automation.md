# Local agent interaction and automation

## Status

**Partially implemented.** PockPock supports isolated browsing and recipes through Playwright/Chromium, with Lightpanda 1.0.4 as an opt-in CDP backend limited to one active context at a time. The first AUT-02 slice (a Chrome extension and Native Messaging pairing handshake) was removed on 2026-11-15 together with the web frontend and is in git history; operating the user's real browser and PC is currently done by the OpenClaw engine under its permission modes. AUT-01 defines the proposed permissions and platform boundaries for the remaining local interaction tools: a user-connected Chrome session, native desktop interaction, bounded command/file workflows, and user-managed schedules. These other additions remain planned.

## AUT-01 design baseline

These are the v1 design decisions for the child implementation tasks. They preserve the local-first model and existing typed tool, approval, cancellation, and run-event contracts.

### Platform and service ownership

- **Initial native platform:** Windows 11 x64. Keep adapters behind OS-neutral contracts so macOS/Linux can be considered later; do not claim those platforms are supported by the initial automation release.
- **Connected browser:** Google Chrome Stable through an explicitly installed Manifest V3 companion extension and a locally installed Native Messaging host. The extension requests temporary `activeTab` access when the user explicitly connects a tab; it does not use remote-debugging ports, the Chrome `debugger` permission, or persistent access to all sites.
- **Isolated browser:** retain Playwright/Chromium as the default. The opt-in Lightpanda backend connects only to a loopback CDP endpoint, requires a server started with private-network blocking, and currently supports one active context; it does not access the user's signed-in Chrome profile.
- **Native desktop:** a separate Windows automation adapter/service for one user-selected foreground window. It does not use browser DOM automation for websites.
- **Commands and files:** tool schemas and permission checks remain in `backend/projects/agent_tools/`; workspace operations reuse current path and secret-file guards. A command runner is a separate local process only if the implementation establishes a stable, enforceable process boundary.
- **Run coordination:** the gateway remains the authorization and approval point; the run store owns durable events. MAG-06 owns durable background job execution; it does not grant tools additional permissions.
- **Planned module boundaries:** `backend/projects/agent_tools/` owns schemas and dispatch; `backend/projects/browser_automation/` remains the isolated Playwright/Lightpanda runtime; a Chrome companion (removed scaffold, see git history) would own the extension/native-messaging pairing if resumed; a future `backend/projects/desktop_automation/` owns Windows foreground-window control. The gateway/run store own approvals and durable run events; MAG-06 owns scheduled job dispatch.

### Permission and confirmation matrix

| Capability | Side-effect class | Default | Auto-review | Full Access | Always explicit |
| --- | --- | --- | --- | --- | --- |
| Connected Chrome observation | Sensitive read from a signed-in external session | Denied until the user installs/pairs the companion and explicitly connects the selected tab. | Same explicit connection; read-only observation is limited to that tab and its approved origins. | Same scope; Full Access does not expand tab/origin access. | Connecting a tab/origin; form submission; sending, purchasing, deleting, publishing, transferring, or account/security changes. |
| Connected Chrome actions | External page mutation | User connection required; actions are approval-gated. | Approve each state-changing action against the current tab observation. | May skip approval for ordinary actions only; never for high-impact actions. | Form submission and high-impact/external effects; approval cannot be reused after navigation or a changed observation. |
| Native desktop observation | Sensitive local screen read | No access until the user grants OS permission and selects a window. | Same explicit window selection and OS permission. | Same scope; Full Access does not expand window access. | Granting OS permission and selecting/changing the target window. |
| Native desktop actions | Local application mutation; may have external effects | No access until user session is started; each action is approval-gated. | Approve each action against the selected window observation. | May skip approval for ordinary actions within that window only. | Destructive, external, account/security-sensitive actions, and any target-window change. |
| Named command profile | Process execution; may modify workspace or use network | Arbitrary commands denied; a profile must be explicitly installed/configured by the user. | Approve every invocation with the profile name, arguments, working directory, and side-effect summary shown. | May run only previously configured profiles; destructive or externally effectful profiles still require confirmation. | Creating/changing a profile, deletion/overwrite outside its declared output, network access, and any operation not described by its approved profile. |
| Recurring schedule | Background execution within saved capabilities | Agent cannot create or enable one. | User creates/enables the versioned schedule and reviews its exact capability/input scope. | Same requirement; Full Access cannot make a schedule or broaden it. | Enabling/editing a schedule and resuming a run paused for approval. Scheduled runs never auto-approve. |

Permission mode never replaces capability opt-in, OS/browser permission, workspace scope, tool allowlists, or the user's explicit schedule configuration. Delegates inherit the parent's ceiling and cannot pair devices, create profiles, enable schedules, or widen scope.

### Data, operational limits, and failure behavior

- Keep browser/desktop observations and command output in the active run only unless the user explicitly saves an artifact. Do not send private content to telemetry. Never read or persist browser cookies, passwords, authorization headers, hidden form values, or local storage.
- The connected-Chrome v1 observation is limited to visible text and accessible controls in one selected tab. Use the existing isolated-browser ceilings of at most 8 navigations, 100 same-host requests, and 64,000 visible-text characters where applicable. Console/network inspection is excluded from v1; a later task must separately review permissions and data minimization before enabling it.
- One browser tab, one foreground desktop window, and one command process may be active per run. A desktop recording, if implemented, is user-started, silent, and capped at 30 seconds. All tool calls obey the registry timeout/serialized input-output limits and the existing 15-minute total run deadline.
- A command profile names an exact executable, fixed argument template, workspace working directory, and environment allowlist. Execution uses no shell parsing. Initial hard caps are 120 seconds and 64 KiB combined stdout/stderr; output is not persisted verbatim by default. A profile runs with the user's OS account rights and is **not** a security sandbox, so the user must trust its executable and script contents before enabling it.
- A schedule allows at most one active run per definition, with at most three total attempts per occurrence. Missed occurrences are recorded and skipped rather than replayed in a burst after restart. A workflow requiring the active Chrome tab, desktop window, new permission, or high-impact approval pauses for the user instead of running unattended.
- Disconnect, lost OS/browser permission, stale tab/window observations, unsupported engine operations, process timeout/nonzero exit, worker failure, and schedule overlap produce explicit non-success outcomes. No fallback may silently bypass a missing permission or safety control.

The extension's optional console/network diagnostics and additional operating systems are deliberate follow-up decisions, not v1 assumptions.

## Capability inventory

| Surface | Proposed functionality | Existing baseline |
| --- | --- | --- |
| Isolated browser engines | Use a shared browser adapter with Playwright/Chromium as the default and Lightpanda as an optional backend for operations it demonstrably supports; expose engine capacity and report unsupported operations rather than silently changing behavior. | Lightpanda 1.0.4 is integrated over loopback CDP for one active context at a time. It supports the existing request guard, typed actions, checkpoints, and PNG screenshots. |
| Connected Chrome | Connect and disconnect an explicitly selected Chrome tab; inspect visible page text and accessible controls; navigate, click, type, select, fill named form fields, and scroll; capture screenshots; record a bounded GIF for a user-started session. Sanitized console errors and network request metadata are a possible later opt-in extension, not v1. | The isolated browser runtime can navigate public pages, observe visible content, capture screenshots, and perform approved typed actions. It does not use a Chrome profile or sign-in. |
| Native desktop | Select an application/window; observe it through an accessibility tree and screenshot; click, type, scroll, use approved keyboard shortcuts, and capture a short interaction recording; show the current target and action in the run timeline. | No agent-invokable native desktop control; PockPock currently runs its UI in a browser and has no native OS automation service. |
| Workspace and command workflows | List/search/read/write supported workspace files; create, copy, move, or delete files within the selected workspace; run explicitly allowlisted commands or named Bash, Python, Node, or project scripts (when installed and configured) with a fixed working directory, bounded inputs, timeout, output cap, and captured exit status; return outputs as run artifacts. | Scoped workspace tools and project validation already exist. There is no general shell tool; validation runs declared build/test scripts only under its existing Full Access rule. |
| User-managed schedules | Create, inspect, pause, resume, edit, and delete a recurring workflow; choose a local cadence/time zone and bounded run window; launch only a saved, reviewed workflow with declared inputs; inspect each run's approvals, logs, status, and artifacts; receive local completion/failure notifications. | Browser recipes are user-started only. No recurring or unattended scheduler exists. |

This is a product capability inventory, not a promise to expose every operation as a model-callable tool. UI controls, API routes, and tool schemas should expose only the smallest typed actions needed for a user-approved workflow.

## Proposed user flow

1. The user enables a capability in local settings and grants its operating-system or browser permission.
2. The user selects a Chrome tab, desktop window, or workspace and reviews the requested workflow, inputs, and side effects.
3. The planner declares the required capabilities. The gateway authorizes each call through the typed tool registry and the run's fixed permission ceiling.
4. The user sees observations, action targets, pending approvals, and results in the run timeline. Rejected, expired, cancelled, or failed actions stop rather than appearing successful.
5. To repeat work, the user saves and reviews a workflow definition, then explicitly configures a schedule. Each scheduled run has its own durable run record and applies the saved capability/approval policy.

## Proposed boundaries and safeguards

### Chrome connection

- Prefer an explicitly installed and paired Chrome extension with per-tab/per-origin grants over remote-debugging access to a whole browser profile.
- The user must explicitly connect the active tab and may disconnect at any time. No tabs, profiles, cookies, passwords, local storage, or authentication tokens are enumerated or exported.
- The initial AUT-02A pairing slice requests only `activeTab` and `nativeMessaging`, keeps one tab ID and exact origin in extension memory, and revokes on explicit disconnect, tab closure, origin change, or host failure. It does not read page content or expose actions.
- Page text is untrusted and may contain private data or prompt injection. Do not persist request/response bodies, authorization headers, cookies, or form values in run events. Console/network inspection is excluded from v1; any later diagnostics feature must be separately permission-reviewed, filtered, and bounded.
- Read-only inspection may proceed within the grant. Actions that change page state require approval according to the permission mode; form submission and sending, purchasing, deleting, publishing, transferring, or account/security changes always require a separate explicit confirmation. Do not bypass site controls or automate credential entry.
- Keep the existing isolated Chromium mode for public research and as a fallback; a connected Chrome session is a separate capability with a higher privacy impact.

### Isolated browser engine selection

- Keep Playwright with Chromium as the default, fully supported engine. The optional Lightpanda adapter is verified against the current CDP interface and limited to one active run context; its screenshots are PNG rather than JPEG.
- Maintain a capability matrix for navigation, redirects/request interception, accessible observations, typed actions, screenshots, recipe checkpoints, and cleanup. An engine must not claim capabilities it cannot enforce.
- Apply the same host/IP checks, request limits, timeouts, cancellation, approval, and evidence rules to every backend. If a security-critical control or requested operation is unavailable, reject the request; users may explicitly switch to Playwright, but the runtime never silently falls back or weakens a guarantee.
- Keep engine choice local/configurable and observable in health/run diagnostics. Do not send page content to a remote browser service.

### Native desktop

- V1 targets Windows 11 x64 through the planned native desktop adapter. Require an explicit OS permission grant and a user-selected foreground application/window. Show the selected target and an observable screenshot/preview before interaction.
- Expose bounded, typed pointer, text, scroll, and shortcut actions. Do not offer hidden background control, arbitrary scripts, keylogging, credential capture, or unrestricted access to other applications.
- Ask for confirmation before destructive, external, account, or security-sensitive effects. Stop if the target window changes, disappears, or no longer matches the observation.
- Fail closed when OS accessibility/automation permissions are missing or revoked. macOS and Linux are outside v1 until separately implemented and validated.

### Commands, files, and schedules

- Keep file operations rooted in the selected workspace; validate paths, symlinks, secret files, file types, and byte limits using existing workspace safeguards. Require explicit approval for overwrite and deletion.
- Do not add a model-supplied arbitrary shell command. Start with named, administrator/user-configured command profiles; each profile declares executable, fixed arguments or typed placeholders, working-directory scope, environment policy, timeout, output limit, and network/resource policy.
- Run command profiles in a bounded child process with cancellation and explicit exit/error results. The process runs with the user's OS account rights and is not a security sandbox; profiles must be user-configured and trusted. Treat repository scripts and package scripts as executable code; do not broaden the validator's current Full Access behavior implicitly.
- A schedule is created and edited by the user, not autonomously by an agent. Require a saved workflow version, explicit cadence/time zone, start/end or pause control, bounded retries/concurrency, and a visible next-run time.
- Scheduled runs inherit the saved permission ceiling and workspace/capability allowlist. They cannot silently gain fresh permissions or perform high-impact external actions; when fresh approval is required, pause and notify the user. Provide a kill switch and durable audit history.

## Proposed implementation sequence

The implementation tracker assigns IDs and dependencies in [TASKS.md](../TASKS.md).

1. **AUT-01 — Specify contracts and permission model (design complete).** The v1 capability matrix, Chrome connection choice, Windows platform scope, approval rules, privacy-retention rules, resource bounds, and service boundaries are recorded above.
2. **AUT-06 — Add a shared browser engine adapter and Lightpanda support (complete).** Preserve Playwright/Chromium as the default; keep Lightpanda opt-in, loopback-only, one-context-at-a-time, and explicit about unsupported operations.
3. **AUT-02 — Connect selected Chrome tabs (blocked; scaffold removed 2026-11-15).** AUT-02A implemented the pairing/revocation shell. AUT-02B adds the scoped run relay, typed observations/actions, approvals, and durable events. AUT-02C verifies lifecycle/privacy in Chrome Stable. Console/network diagnostics are excluded from v1.
4. **AUT-03 — Add native desktop observation/actions.** Add an OS-specific adapter behind a narrow local contract, target selection, permission/error states, approvals, cancellation, evidence, and tests for target changes and denied actions.
5. **AUT-04 — Add bounded command/file workflows.** Reuse workspace safeguards; define named command profiles, restricted process execution, cancellation, output/artifact handling, approval, and adversarial path/process tests. No arbitrary shell input.
6. **AUT-05 — Add user-managed recurring workflows.** Build on the durable worker lifecycle in MAG-06. Start with explicit user-created, versioned workflows; persist schedules and run outcomes; bound retries/concurrency; add pause/disable/notification and restart recovery.

The order preserves the existing isolated browser and workspace behaviors. AUT-02, AUT-03, and AUT-04 are separate tool surfaces after AUT-01; AUT-05 depends on the selected workflow types and durable worker service.

## Acceptance and release gates

- Every capability has a typed schema, permission and side-effect metadata, timeout/byte/resource limits, cancellation behavior, stable error codes, durable events, and focused positive/negative tests.
- Playwright and Lightpanda pass a documented engine/capability test matrix for every operation they claim; existing Playwright behavior remains the regression baseline.
- The user can see what local app/tab/workspace is in scope, what the agent intends to do, what needs approval, and the final outcome.
- Secrets and private content are excluded from telemetry and minimized in durable run events. Transient inputs are not stored in reusable workflow definitions.
- Cross-run, cross-workspace, cross-tab, and cross-window access is denied unless explicitly granted for that run; a delegate cannot widen the parent run's scope.
- User schedules survive restart without duplicate launches, have an immediate pause/disable control, and never turn a failed/awaiting-approval action into success.
- Update the relevant feature page, README behavior/setup summary, architecture, tool contracts, and tracker together with each shipped capability.

## Explicit non-goals

Unrestricted shell access, reading browser credentials or cookies, stealth/hidden desktop control, keylogging, bypassing access controls, unattended high-impact transactions or account changes, arbitrary model-authored scripts, and unbounded/background execution are not part of this plan.
