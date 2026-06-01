import { describe, expect, it } from "vitest";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

const FORBIDDEN_PATTERNS = [
  /fc-data\.ssi\.com\.vn/,
  /fc-tradeapi\.ssi\.com\.vn/,
  /SSI_CONSUMER_/,
  /consumerSecret/i,
];

const SOURCE_ROOTS = ["src/app", "src/components", "src/hooks", "src/lib", "src/features"];

const ROOT = path.resolve(__dirname, "..");

async function walk(dir: string): Promise<string[]> {
  const entries = await readdir(dir, { withFileTypes: true });
  const out: string[] = [];
  for (const entry of entries) {
    if (entry.name.startsWith(".") || entry.name === "node_modules") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...(await walk(full)));
    } else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

describe("frontend security", () => {
  it("never references SSI endpoints or credential names directly", async () => {
    const files: string[] = [];
    for (const subdir of SOURCE_ROOTS) {
      files.push(...(await walk(path.join(ROOT, subdir))));
    }
    expect(files.length).toBeGreaterThan(0);

    const offenders: { file: string; pattern: string }[] = [];
    for (const file of files) {
      const text = await readFile(file, "utf-8");
      for (const pattern of FORBIDDEN_PATTERNS) {
        if (pattern.test(text)) {
          offenders.push({ file, pattern: pattern.toString() });
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
