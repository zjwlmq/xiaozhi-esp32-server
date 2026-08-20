import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const modulePath = new URL("../src/utils/nixiAccessPolicy.js", import.meta.url);
const source = await readFile(modulePath, "utf8");
const imported = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

const { isNixiRolepackPrompt, normalizeNixiAccessPolicy } = imported;

test("recognizes only supported nixi rolepack directives", () => {
  assert.equal(isNixiRolepackPrompt("@rolepack nixi/wu\ncanon=novel"), true);
  assert.equal(isNixiRolepackPrompt("\n @rolepack nixi/duo audience=daughter"), true);
  assert.equal(isNixiRolepackPrompt("@rolepack other/duo"), false);
  assert.equal(isNixiRolepackPrompt("prefix @rolepack nixi/chi"), false);
});

test("normalizes access policy fail-closed and deduplicates user ids", () => {
  assert.deepEqual(normalizeNixiAccessPolicy({ mode: "public", whitelistUserIds: [3, 3, -1, "4"] }), {
    mode: "public",
    whitelistUserIds: [3]
  });
  assert.deepEqual(normalizeNixiAccessPolicy({ mode: "unknown", whitelistUserIds: null }), {
    mode: "owner",
    whitelistUserIds: []
  });
});

test("role page wires the admin policy card and API endpoints", async () => {
  const root = new URL("../src/", import.meta.url);
  const roleConfig = await readFile(new URL("views/roleConfig.vue", root), "utf8");
  const component = await readFile(new URL("components/NixiAccessPolicySettings.vue", root), "utf8");
  const api = await readFile(new URL("apis/module/agent.js", root), "utf8");
  assert.match(roleConfig, /<nixi-access-policy-settings v-model="form\.systemPrompt"/);
  assert.match(component, /仅站长/);
  assert.match(component, /指定账号/);
  assert.match(component, /全站公开/);
  assert.match(component, /不能靠手写 @rolepack 指令绕过/);
  assert.match(api, /\/nixi-rolepack\/access-policy/);
});

test("backend enforces the policy on save and device runtime", async () => {
  const repoRoot = new URL("../../", import.meta.url);
  const agentController = await readFile(
    new URL("manager-api/src/main/java/xiaozhi/modules/agent/controller/AgentController.java", repoRoot),
    "utf8"
  );
  const accessController = await readFile(
    new URL("manager-api/src/main/java/xiaozhi/modules/agent/controller/NixiRolepackAccessController.java", repoRoot),
    "utf8"
  );
  const accessService = await readFile(
    new URL("manager-api/src/main/java/xiaozhi/modules/agent/service/NixiRolepackAccessService.java", repoRoot),
    "utf8"
  );
  const configService = await readFile(
    new URL("manager-api/src/main/java/xiaozhi/modules/config/service/impl/ConfigServiceImpl.java", repoRoot),
    "utf8"
  );
  const migration = await readFile(
    new URL("manager-api/src/main/resources/db/changelog/202608201500.sql", repoRoot),
    "utf8"
  );

  assert.match(agentController, /assertPromptAllowed\(SecurityUser\.getUserId\(\), dto\.getSystemPrompt\(\)\)/);
  assert.match(configService, /enforceRuntimePrompt\(\s*agent\.getUserId\(\), agent\.getSystemPrompt\(\)\s*\)/s);
  assert.match(configService, /buildModuleConfig\(\s*agent\.getAgentName\(\),\s*effectivePrompt,/s);
  assert.match(accessController, /@PutMapping[\s\S]*@RequiresPermissions\("sys:role:superAdmin"\)/);
  assert.match(accessService, /if \(isSuperAdmin\(user\)\) \{\s*return true;/s);
  assert.match(accessService, /MODE_OWNER/);
  assert.match(accessService, /MODE_WHITELIST/);
  assert.match(accessService, /MODE_PUBLIC/);
  assert.match(migration, /\{"mode":"owner","whitelistUserIds":\[\]\}/);
});
