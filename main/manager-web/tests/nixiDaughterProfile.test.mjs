import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { pathToFileURL } from "node:url";

const modulePath = new URL("../src/utils/nixiDaughterProfile.js", import.meta.url);
const source = await readFile(modulePath, "utf8");
const imported = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

const {
  decodeDaughterProfile,
  encodeDaughterProfile,
  getDaughterEditorState,
  updateDaughterSettings
} = imported;

const original = [
  "@rolepack nixi/duo",
  "canon=novel",
  "stage=S8",
  "audience=observer",
  "# keep-this-comment"
].join("\n");

test("daughter profile round-trips Chinese text without loss", () => {
  const encoded = encodeDaughterProfile({
    name: "小满",
    calls_wu: "吴爸",
    calls_chi: "池爸",
    family_rules: "先听女儿说完，再商量；不替她决定。"
  });
  const decoded = decodeDaughterProfile(encoded);
  assert.equal(decoded.name, "小满");
  assert.equal(decoded.calls_wu, "吴爸");
  assert.equal(decoded.family_rules, "先听女儿说完，再商量；不替她决定。");
  assert.match(encoded, /^[A-Za-z0-9_-]+$/);
});

test("enabling daughter mode preserves canon and stage options", () => {
  const enabled = updateDaughterSettings(original, true, {
    name: "小满",
    age_stage: "adult",
    origin: "co_parented"
  });
  assert.match(enabled, /^@rolepack nixi\/duo/m);
  assert.match(enabled, /^canon=novel$/m);
  assert.match(enabled, /^stage=S8$/m);
  assert.match(enabled, /^audience=daughter$/m);
  assert.match(enabled, /^daughter_profile=[A-Za-z0-9_-]+$/m);
  assert.match(enabled, /^# keep-this-comment$/m);
  const state = getDaughterEditorState(enabled);
  assert.equal(state.enabled, true);
  assert.equal(state.profile.name, "小满");
});

test("disabling daughter mode removes profile and restores mode default", () => {
  const enabled = updateDaughterSettings(original, true, { name: "小满" });
  const disabled = updateDaughterSettings(enabled, false, {});
  assert.doesNotMatch(disabled, /daughter_profile=/);
  assert.match(disabled, /^audience=observer$/m);
});

test("component is wired into role configuration and exposes session-fiction notice", async () => {
  const root = new URL("../src/", import.meta.url);
  const roleConfig = await readFile(new URL("views/roleConfig.vue", root), "utf8");
  const component = await readFile(new URL("components/NixiDaughterSettings.vue", root), "utf8");
  assert.match(roleConfig, /<nixi-daughter-settings v-model="form\.systemPrompt"/);
  assert.match(roleConfig, /import NixiDaughterSettings/);
  assert.match(component, /启用女儿身份/);
  assert.match(component, /session fiction/);
});
