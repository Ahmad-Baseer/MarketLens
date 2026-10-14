import "server-only";
import { readFile } from "node:fs/promises";
import path from "node:path";
import type { HistoryIndex, HistoryYear, SignalDetail, Today } from "./types";

/**
 * Where the pipeline's JSON lives.
 *  - MBF_DATA_URL (production): a base URL the evening job publishes to; responses are
 *    cached for REVALIDATE seconds, so a new evening's signals appear within minutes.
 *  - MBF_DATA_DIR (local): a directory, by default ../data/web next to this app.
 */
const DATA_URL = process.env.MBF_DATA_URL?.replace(/\/+$/, "");
// local reads only: keep the bundler from tracing the data folder into the server build
const DATA_DIR = process.env.MBF_DATA_DIR ?? path.join(/*turbopackIgnore: true*/ process.cwd(), "..", "data", "web");
export const REVALIDATE = 300;

const ID_RE = /^[A-Z0-9_]+-[A-Z0-9]+-\d{8}$/;

async function load<T>(rel: string): Promise<T | null> {
  if (DATA_URL) {
    const res = await fetch(`${DATA_URL}/${rel}`, { next: { revalidate: REVALIDATE } });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`data fetch ${rel}: HTTP ${res.status}`);
    return (await res.json()) as T;
  }
  try {
    return JSON.parse(await readFile(path.join(/*turbopackIgnore: true*/ DATA_DIR, rel), "utf-8")) as T;
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw e;
  }
}

/** today.json plus how many calendar days old its session is, measured when it's loaded. */
export async function getToday(): Promise<(Today & { age_days: number }) | null> {
  const t = await load<Today>("today.json");
  if (!t) return null;
  const asof = Date.parse(t.asof.slice(0, 10) + "T00:00:00Z");
  return { ...t, age_days: Math.floor((Date.now() - asof) / 86_400_000) };
}
export const getHistoryIndex = () => load<HistoryIndex>("history.json");

export function getHistoryYear(year: number) {
  if (!Number.isInteger(year) || year < 2000 || year > 2100) return Promise.resolve(null);
  return load<HistoryYear>(`history/${year}.json`);
}

export function getSignal(id: string) {
  // ids come from the URL: only ever read files named like a signal id
  if (!ID_RE.test(id)) return Promise.resolve(null);
  return load<SignalDetail>(`signals/${id}.json`);
}
