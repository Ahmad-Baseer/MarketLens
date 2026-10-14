import { NextResponse, type NextRequest } from "next/server";
import { COOKIE, gateEnabled, isValidToken } from "@/lib/access";

// Runs before every page: when invite codes are configured, visitors without a valid
// access cookie are sent to /access first.
export async function proxy(req: NextRequest) {
  if (!gateEnabled()) return NextResponse.next();
  if (await isValidToken(req.cookies.get(COOKIE)?.value)) return NextResponse.next();
  const url = req.nextUrl.clone();
  url.pathname = "/access";
  url.search = `?next=${encodeURIComponent(req.nextUrl.pathname + req.nextUrl.search)}`;
  return NextResponse.redirect(url);
}

export const config = {
  // everything except the access page itself and static assets
  matcher: ["/((?!access|_next/static|_next/image|favicon.ico|icon.svg|robots.txt).*)"],
};
