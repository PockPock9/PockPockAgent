# Problem reports and Maintenance

Users report a reply that hung, failed or was wrong with the **Report** button under it. Reports stay on the PC and are listed on the **Maintenance** page, where they can be reviewed, corrected or deleted. They are the input for the Maintenance Manager (LRN-04 in [`TASKS.md`](../TASKS.md), planned), which will reproduce a reported problem, fix it with a documentation update, run the checks, and open a draft pull request after the user approves.

## User flow

1. Under any assistant reply, press **Report** (the flag button next to **Copy reply**).
2. Choose what went wrong: **It hung or never finished**, **It failed**, **The result was wrong**, or **Something else**. A stopped reply starts on "hung", an error reply on "failed".
3. Optionally describe what happened and what you expected.
4. **What will be saved** shows the exact captured exchange after redaction, and what was hidden (for example "2 folder paths").
5. **Save report**. The dialog confirms and offers **Open Maintenance**.
6. **Maintenance** (sidebar) lists reports, newest first, with their category, status, chat, mode and age. Open one to change its category, status (**Open**, **Being fixed**, **Fixed**, **Won't fix**) or description, read the full capture, or delete it.

## What a report contains

| Field | Content |
|---|---|
| `category`, `description`, `status` | The user's choice and text (max 4,000 characters), status starts `open` |
| `capture.appVersion`, `platform`, `engine`, `model`, `chatTitle`, `createdAt` | Where it happened |
| `capture.userMessage`, `attachments` | The user message before the reply; attachment **names only**, never contents |
| `capture.reply`, `status`, `notice` | The reply text and its outcome |
| `capture.plan` | PockPock Agent plan goal, steps and decision |
| `capture.steps` | Each step's label, status, error detail and duration |
| `capture.approvals` | Each approval's title, description (command, path or URL) and outcome |
| `capture.timing` | The Thinking/Planning/Waiting/Working/Total breakdown |
| `redactions` | How many folder paths, user names, email addresses and keys or tokens were hidden |

Strings are capped (20,000 characters each, 120 steps, 60 approvals); unknown fields are dropped.

## Privacy

- Reports never leave the PC. They are stored as one JSON file each in `<app data>/reports/` (`%APPDATA%\PockPock Agent\reports` on Windows, `~/Library/Application Support/PockPock Agent/reports` on macOS), at most 200 (the oldest are removed).
- Before storing, the main process redacts every string in the capture and the description: the user's home folder in any slash style becomes `~`, the user name `<user>`, email addresses `<email>`, and API keys, tokens, `password=`/`token=` values and long opaque strings `<secret>`. The dialog shows the redacted capture before saving.
- Redaction is pattern-based. It cannot recognise every personal detail in free text (a name or address typed into a prompt), so the preview is there for the user to check.

## Modules and contract

| Module | Role |
|---|---|
| `desktop/src/lib/reports.ts` | `buildCapture` (one reply and the user message before it), labels, `captureText`, `describeRedactions` |
| `desktop/src/components/ReportDialog.tsx` | The dialog: modal, focus kept inside, Escape closes, buttons always visible |
| `desktop/src/pages/MaintenancePage.tsx` | List and detail views |
| `desktop/electron/reports.cjs` | `ReportStore` (validate, redact, store, prune), `prepareCapture`, `redactText`; unit tests in `reports.test.cjs` |

IPC (preload `window.pockpock.reports`, all registered with `handle()`): `preview(capture)` returns the redacted capture and counts without saving; `create({ category, description, capture })`; `list()` (without captures); `get(id)`; `update(id, { category?, status?, description? })`; `delete(id)`. Ids must match `r-<base36>-<8 hex>`, so a renderer cannot read or delete other files; categories and statuses are checked against fixed lists.

## Failure states

- The capture cannot be built (for example the app info call fails): the dialog shows the error and Save stays disabled.
- Saving fails (disk full, permissions): the error is shown and the form keeps what was typed.
- A report file is unreadable: it is skipped in the list; opening a missing id shows "Unknown report."

## Verification

- `npm test` in `desktop/` (redaction, capture sanitising, store create/list/update/delete, id checks).
- In the app with a temporary profile (`POCKPOCK_DESKTOP_USER_DATA`), in PockPock Dark and Feather at 1440 px and 820 px: Report opens with focus inside and closes on Escape; the preview hides the home folder; the stored file contains no home folder, email or attachment contents; status changes persist; delete removes the file; no horizontal overflow or console errors.
