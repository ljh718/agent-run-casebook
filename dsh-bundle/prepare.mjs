// Copies the bundled skill into the DSH user skills directory so DSH discovers it.
// Runs during pnpm install of this package (prepare lifecycle). pnpm >= 10 may ask
// to approve the build script; see DSH-MARKET.md in the repository root.
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const dshHome = process.env.DSH_HOME && process.env.DSH_HOME.trim() !== ""
  ? process.env.DSH_HOME
  : join(homedir(), ".dsh");
const target = join(dshHome, "skills", "agent-run-casebook");
const source = join(here, "skill");

if (!existsSync(source)) {
  console.error("[agent-run-casebook] missing skill/ directory next to prepare.mjs");
  process.exit(1);
}
mkdirSync(dirname(target), { recursive: true });
rmSync(target, { recursive: true, force: true });
cpSync(source, target, { recursive: true });
console.log(`[agent-run-casebook] skill installed to ${target}`);
