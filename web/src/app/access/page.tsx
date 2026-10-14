import type { Metadata } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Card } from "@/components/ui";
import { COOKIE, MAX_AGE, gateEnabled, isValidCode, safeNext, tokenFor } from "@/lib/access";

export const metadata: Metadata = { title: "Invite only" };

async function unlock(formData: FormData) {
  "use server";
  const code = String(formData.get("code") ?? "");
  const next = safeNext(String(formData.get("next") ?? "/"));
  if (!isValidCode(code)) redirect(`/access?error=1&next=${encodeURIComponent(next)}`);
  (await cookies()).set(COOKIE, await tokenFor(code.trim()), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: MAX_AGE,
  });
  redirect(next);
}

type Props = { searchParams: Promise<{ next?: string; error?: string }> };

export default async function AccessPage({ searchParams }: Props) {
  const sp = await searchParams;
  if (!gateEnabled()) redirect("/");
  return (
    <div className="mx-auto mt-10 max-w-md">
      <Card className="p-6 sm:p-8">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">MarketLens is invite-only for now</h1>
        <p className="mt-2 text-sm leading-relaxed text-ink-2">
          Enter the access code you were given. You&apos;ll stay signed in on this device for 90 days.
        </p>
        <form action={unlock} className="mt-6 space-y-3">
          <input type="hidden" name="next" value={safeNext(sp.next)} />
          <label htmlFor="code" className="block text-sm font-medium text-ink">
            Access code
          </label>
          <input
            id="code"
            name="code"
            required
            autoComplete="off"
            autoFocus
            className="w-full rounded-xl border border-line bg-surface-2 px-4 py-2.5 text-ink placeholder:text-ink-3"
            placeholder="e.g. ahmad-7f3k"
          />
          {sp.error && <p className="text-sm text-loss">That code isn&apos;t valid. Check it and try again.</p>}
          <button
            type="submit"
            className="w-full rounded-xl bg-brand px-4 py-2.5 text-sm font-semibold text-surface transition-colors hover:bg-brand-2"
          >
            Continue
          </button>
        </form>
      </Card>
    </div>
  );
}
