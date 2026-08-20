#!/usr/bin/env node
/**
 * Build EDPPMT into dist/EDPPMT for copying into the EDMC plugins folder.
 *
 * Usage:  node scripts/build.mjs
 * Output: dist/EDPPMT/
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const sourceDir = path.join(root, "plugin");
const outputDir = path.join(root, "dist", "EDPPMT");

const SKIP_NAMES = new Set(["__pycache__", ".pyc"]);

function copyRecursive(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (SKIP_NAMES.has(entry.name)) continue;
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyRecursive(srcPath, destPath);
    } else if (entry.isFile() && !entry.name.endsWith(".pyc")) {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function cleanDir(dir) {
  if (fs.existsSync(dir)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

cleanDir(outputDir);
copyRecursive(sourceDir, outputDir);

const version = fs
  .readFileSync(path.join(sourceDir, "__init__.py"), "utf8")
  .match(/__version__\s*=\s*["']([^"']+)["']/)?.[1];

console.log(`Built EDPPMT v${version ?? "?"} -> ${outputDir}`);
console.log("");
console.log("Copy to EDMC plugins folder:");
console.log("  %LOCALAPPDATA%\\EDMarketConnector\\plugins\\EDPPMT");
