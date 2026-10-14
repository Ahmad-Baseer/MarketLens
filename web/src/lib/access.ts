// Invite-only access. Set ACCESS_CODES="alice-7f3k,bob-q9x2" (one per person) and a long random
// ACCESS_SECRET. The cookie holds a hash of the secret and the visitor's code, so deleting a
// code from ACCESS_CODES locks that person out. With no ACCESS_CODES the site is open.

export const COOKIE = "ml_access";
export const MAX_AGE = 60 * 60 * 24 * 90; // 90 days

export function accessCodes(): string[] {
  return (process.env.ACCESS_CODES ?? "")
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);
}

export const gateEnabled = () => accessCodes().length > 0;

export async function tokenFor(code: string): Promise<string> {
  const secret = process.env.ACCESS_SECRET ?? "";
  const data = new TextEncoder().encode(`${secret}:${code}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

function sameString(a: string, b: string) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function isValidToken(token: string | undefined): Promise<boolean> {
  if (!token) return false;
  for (const code of accessCodes()) if (sameString(token, await tokenFor(code))) return true;
  return false;
}

export function isValidCode(code: string): boolean {
  return accessCodes().some((c) => sameString(c, code.trim()));
}

/** Only ever redirect back to a path on this site. */
export function safeNext(next: string | null | undefined): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}
