export const NIXI_ACCESS_MODES = Object.freeze({
  owner: "仅站长",
  whitelist: "指定账号",
  public: "全站公开"
});

export function isNixiRolepackPrompt(prompt) {
  if (typeof prompt !== "string") return false;
  const first = prompt.split(/\r?\n/).map(line => line.trim()).find(Boolean) || "";
  return /^@rolepack\s+nixi\/(wu|chi|duo)(?:\s|$)/.test(first);
}

export function normalizeNixiAccessPolicy(policy = {}) {
  const mode = Object.prototype.hasOwnProperty.call(NIXI_ACCESS_MODES, policy.mode)
    ? policy.mode
    : "owner";
  const whitelistUserIds = Array.isArray(policy.whitelistUserIds)
    ? [...new Set(policy.whitelistUserIds.filter(id => Number.isInteger(id) && id > 0))]
    : [];
  return { mode, whitelistUserIds };
}
