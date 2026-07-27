import type { AppStatus } from "./types";

/**
 * Statuses at which the generation pipeline is done acting on an
 * application: no further automatic transition will happen without a user
 * action (Generate, Retry, Regenerate, or pasting text). Screens use this to
 * decide whether to keep polling and whether to show a working/spinner
 * state.
 *
 * This is the single source of truth for "terminal" — DashboardScreen and
 * ApplicationScreen each used to keep their own copy of this list, and the
 * copies drifted apart (ApplicationScreen's was missing "not_started"),
 * which left that screen polling forever for a job that had not been
 * generated yet. Both screens must import this constant rather than
 * declaring their own.
 */
export const TERMINAL_STATUSES: AppStatus[] = ["not_started", "ready", "error", "needs_paste"];
