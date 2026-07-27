// Records what the committed bundle was built from.
//
// `frontend/dist` is committed and served by backend/app/main.py, so it is a
// source artifact: a commit that changes frontend/src without rebuilding ships
// a UI nobody wrote. Nothing in either test suite reads the built asset, so
// that divergence is invisible. This writes dist/build-inputs.sha256 after
// every build; tests/test_frontend_bundle.py recomputes it and fails when the
// sources have moved on.
//
// Kept byte-identical to build_inputs() in tests/test_frontend_bundle.py:
// same file set, same CRLF->LF normalization, same `sha256  path` line format.
// Any drift between the two shows up there as a named added/missing path.
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FRONTEND = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DIST = join(FRONTEND, "dist");

const ROOT_INPUTS = [
  "index.html",
  "vite.config.ts",
  "tsconfig.json",
  "package.json",
  "package-lock.json",
];

// Vite's entry graph starts at index.html and never reaches these, so they
// cannot change the emitted asset. Hashing them would demand a rebuild after
// every test-only commit.
const isTestSource = (rel) => {
  const name = rel.split("/").pop();
  return name === "test-setup.ts" || name.includes(".test.");
};

const digest = (absPath) =>
  createHash("sha256")
    // CRLF -> LF: core.autocrlf is true and .gitattributes leaves .ts/.tsx
    // alone, so the same commit is CRLF on Windows and LF elsewhere.
    .update(readFileSync(absPath).toString("binary").split("\r\n").join("\n"), "binary")
    .digest("hex");

const walk = (dir, relBase) => {
  const found = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const rel = `${relBase}/${entry.name}`;
    const abs = join(dir, entry.name);
    if (entry.isDirectory()) found.push(...walk(abs, rel));
    else if (entry.isFile() && !isTestSource(rel)) found.push(rel);
  }
  return found;
};

const inputs = [];
for (const name of ROOT_INPUTS) {
  const abs = join(FRONTEND, name);
  try {
    if (statSync(abs).isFile()) inputs.push(name);
  } catch {
    // Absent inputs are skipped on both sides; the test's path-set diff is
    // what notices if one appears or disappears between builds.
  }
}
inputs.push(...walk(join(FRONTEND, "src"), "src"));
inputs.sort();

try {
  if (!statSync(DIST).isDirectory()) throw new Error("not a directory");
} catch {
  console.error(`stamp-build: ${DIST} does not exist - did the build fail?`);
  process.exit(1);
}

const manifest = inputs.map((rel) => `${digest(join(FRONTEND, rel))}  ${rel}\n`).join("");
writeFileSync(join(DIST, "build-inputs.sha256"), manifest, "utf8");
console.log(`stamp-build: recorded ${inputs.length} build inputs`);
