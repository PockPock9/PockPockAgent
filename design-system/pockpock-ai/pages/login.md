# Login Page Overrides

> **PROJECT:** PockPock AI
> **Updated:** 2026-11-12
> **Page Type:** Local demo sign-in form

> Rules in this file **override** the Master file.
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Layout

- **Desktop:** Two-column composition, with product context beside a focused
  sign-in panel.
- **Mobile:** Stack the context and form; keep the form controls full-width.
- **Max Width:** 1120px, centered with safe page padding.

### States

- **Empty:** Explain that no demo credentials have been submitted.
- **Loading:** Disable submission only while the local demo transition runs.
- **Error:** Show a focusable summary with links and inline messages for invalid fields.
- **Success:** Confirm the local demo submission; state plainly that no account
  or authentication service was contacted.

### Typography

- Use the project body face for the heading and form. Reserve the mono face for
  small technical labels.

### Color and Components

- Use the Master palette and existing button/input conventions. Inputs have
  persistent visible labels; error text is associated with its field.
- Avoid external sign-in providers, password persistence, and misleading
  recovery links in this isolated demo.
