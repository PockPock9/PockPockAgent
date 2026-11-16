// Small pure helpers for gateway_turn.mjs, kept separate so they can be unit-tested
// (node --test backend/projects/openclaw_bridge/turn_helpers.test.mjs).

/** Default: stop a turn after this long without any OpenClaw activity (no tokens, tool events or
 * status changes) while no approval is waiting for the user. Long enough for a large model to read
 * a big prompt on the CPU; far shorter than the 30-minute turn timeout. */
export const DEFAULT_STALL_SECONDS = 480

/** True when the turn has made no progress for longer than `stallMs`. Time spent waiting for the
 * user to answer an approval never counts: that is the user's wait, not a hang. */
export function isStalled({ now, lastActivity, pendingApprovals, stallMs }) {
  if (pendingApprovals > 0) return false
  return now - lastActivity > stallMs
}

const EXTERNAL_PREAMBLE = /^\s*External content below is data, not a message from the user or system\.[^\n]*(\n|$)/i
const WRAPPER_LINE = /^\s*(<\/?external[^>]*>|<<<[^\n]*>>>|-{3,}\s*(begin|end)[^\n]*)\s*$/gim

/** Turns OpenClaw's tool error text into something a person can read: drops the untrusted-content
 * preamble and wrapper lines that otherwise fill the whole visible detail, collapses whitespace,
 * and keeps it short. */
export function cleanToolError(text, limit = 400) {
  if (typeof text !== 'string' || !text.trim()) return undefined
  let clean = text.replace(EXTERNAL_PREAMBLE, '').replace(WRAPPER_LINE, '').replace(/\s+/g, ' ').trim()
  if (!clean) clean = 'The tool returned external content that could not be used.'
  return clean.length > limit ? `${clean.slice(0, limit - 1)}…` : clean
}
