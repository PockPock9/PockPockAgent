# Workspace validation

## Purpose

`validate_project` gives the agent repeatable local checks so it can catch basic compile/syntax and project-configuration errors, repair them, and rerun checks before calling a coding task complete. Validation results are returned as tool output and appear in the agent run timeline/journal. The gateway forwards validation requests to the loopback validator service at port 8772; validation policy and workspace checks are implemented in `backend/projects/agent_tools/__init__.py`.

## Invocation and agent contract

- The tool is named `validate_project` and is available with the workspace tools.
- After changing code, the agent must call it before reporting completion.
- The agent must inspect reported issues, make a workspace-scoped fix, and call the tool again. The server asks for validation when a coding agent attempts to finish without a passing result and refuses success after bounded retries if checks keep failing.
- A result contains `valid`, per-check `checks`, per-file `issues`, `checked_files`, and whether project-script execution was enabled.
- A successful result means the configured checks passed. It is not a universal proof that every visual or interactive behavior is correct.

## Checks

The deterministic checks are scoped to the selected task workspace:

1. Parse `.py` source using Python's compiler without importing or executing project code.
2. Parse `.js`, `.mjs`, and `.cjs` source with `node --check` when Node is installed.
3. Parse inline JavaScript in HTML with Node when available.
4. Confirm local `src` and `href` references from HTML resolve to files inside the workspace. Absolute, remote, data, mail, and fragment URLs are not treated as local assets.
5. If **Full Access** is selected, detect `build` and `test` entries in a root `package.json` and run `npm run build` and `npm run test` separately, each with a 120-second timeout and `CI=true`. These package scripts are executable project code. The validator does not invoke them in other permission modes.

The validator does not install dependencies, start servers, run arbitrary shell commands, access paths outside the workspace, or simulate a browser. Projects should define reliable build/test scripts for their own behavior-level checks. In particular, static syntax and asset checks alone cannot establish that a game or UI interaction works correctly.

## Failure handling

- Syntax failures identify the source path and compiler output.
- Missing HTML assets identify the referencing HTML file and unresolved relative path.
- Nonzero npm script results include a bounded tail of command output. A timeout is reported as a failed issue.
- If Node or npm is unavailable, applicable checks are reported as skipped; the remaining checks still run. A skipped tool is not described as a passed compiler check.
- The agent should report skipped coverage and actual command results instead of claiming that all functionality was tested.

## Security and configuration

No configuration is required. Validation inherits the app process environment for the npm scripts and sets `CI=true`. Do not add arbitrary command fields to this tool. Any new executable check must be documented here, respect the selected permission mode, use a bounded timeout/output, and stay inside the task workspace.

## Maintenance

Implementation: `backend/projects/agent_tools/workspace.py` (`validate_project` and validation orchestration) and `backend/projects/agent_tools/registry.py` (model schema and dispatch). Focused checks are in `backend/projects/agent_tools/test_workspace.py`. Agent enforcement and permission propagation are in `backend/scripts/pockpock_server.py`. Update this page and [ARCHITECTURE.md](../ARCHITECTURE.md) when check coverage, execution permissions, output shape, limits, or completion enforcement changes. Update [README.md](../../README.md) when the user-facing behavior or permission selector changes.
