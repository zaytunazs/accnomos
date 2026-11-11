/**
 * The last few runtime calls that failed in this tab (method, path without its query, status, the first 200
 * characters of the message), kept in memory only. Sent with a support ticket only when the user ticks
 * "Attach recent errors"; amounts are masked by the runtime unless they also tick "Include financial details".
 */
export interface RecentError {
  at: string;
  method: string;
  path: string;
  status: number;
  message: string;
}

const MAX = 10;
const errors: RecentError[] = [];

export function recordError(method: string, path: string, status: number, message: string): void {
  if (path.startsWith("/support")) return; // not the ticket's own calls
  errors.push({ at: new Date().toISOString(), method: method.slice(0, 10), path: path.split("?")[0].slice(0, 200), status, message: message.slice(0, 200) });
  if (errors.length > MAX) errors.splice(0, errors.length - MAX);
}

export const recentErrors = (): RecentError[] => errors.slice().reverse();
