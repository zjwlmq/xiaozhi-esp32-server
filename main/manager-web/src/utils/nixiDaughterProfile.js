const NIXI_DIRECTIVE_RE = /^@rolepack\s+nixi\/(wu|chi|duo)$/;
const PROFILE_OPTION = "daughter_profile";
const BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

export const DEFAULT_DAUGHTER_PROFILE = Object.freeze({
  schema_version: 1,
  name: "女儿",
  age_stage: "adult",
  origin: "unspecified",
  calls_wu: "吴爸",
  calls_chi: "池爸",
  wu_calls: "闺女",
  chi_calls: "丫头",
  wu_style: "嘴上会算账和追问细节，实际会照顾，但尊重女儿自己做决定",
  chi_style: "话少，优先处理问题和提供保护，但不能替女儿决定未说明的想法",
  family_rules: "两人发生分歧时不把女儿当裁判，不用原著关系压过女儿当下明确表达的边界"
});

const PROFILE_LIMITS = Object.freeze({
  name: 24,
  calls_wu: 24,
  calls_chi: 24,
  wu_calls: 24,
  chi_calls: 24,
  wu_style: 120,
  chi_style: 120,
  family_rules: 240
});

const AGE_STAGES = new Set(["child", "teen", "adult"]);
const ORIGINS = new Set(["unspecified", "adopted", "co_parented"]);

function cloneDefaults() {
  return { ...DEFAULT_DAUGHTER_PROFILE };
}

function utf8Encode(text) {
  return Array.from(unescape(encodeURIComponent(text)), (char) => char.charCodeAt(0));
}

function utf8Decode(bytes) {
  const binary = bytes.map((value) => String.fromCharCode(value)).join("");
  return decodeURIComponent(escape(binary));
}

function bytesToBase64(bytes) {
  let output = "";
  for (let index = 0; index < bytes.length; index += 3) {
    const first = bytes[index];
    const second = index + 1 < bytes.length ? bytes[index + 1] : 0;
    const third = index + 2 < bytes.length ? bytes[index + 2] : 0;
    const value = (first << 16) | (second << 8) | third;
    output += BASE64_ALPHABET[(value >> 18) & 63];
    output += BASE64_ALPHABET[(value >> 12) & 63];
    output += index + 1 < bytes.length ? BASE64_ALPHABET[(value >> 6) & 63] : "=";
    output += index + 2 < bytes.length ? BASE64_ALPHABET[value & 63] : "=";
  }
  return output;
}

function base64ToBytes(value) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(padded)) {
    throw new Error("女儿设定编码格式错误");
  }
  const bytes = [];
  for (let index = 0; index < padded.length; index += 4) {
    const values = padded
      .slice(index, index + 4)
      .split("")
      .map((char) => (char === "=" ? 0 : BASE64_ALPHABET.indexOf(char)));
    if (values.some((item) => item < 0)) {
      throw new Error("女儿设定编码格式错误");
    }
    const combined = (values[0] << 18) | (values[1] << 12) | (values[2] << 6) | values[3];
    bytes.push((combined >> 16) & 255);
    if (padded[index + 2] !== "=") bytes.push((combined >> 8) & 255);
    if (padded[index + 3] !== "=") bytes.push(combined & 255);
  }
  return bytes;
}

function normalizeText(value, limit, fallback) {
  const normalized = String(value ?? "")
    .replace(/[\r\n]+/g, "；")
    .replace(/[{}<>\u0000-\u001f\u007f]/g, "")
    .trim()
    .slice(0, limit);
  return normalized || fallback;
}

export function normalizeDaughterProfile(profile = {}) {
  const defaults = cloneDefaults();
  const normalized = { schema_version: 1 };
  for (const [key, limit] of Object.entries(PROFILE_LIMITS)) {
    normalized[key] = normalizeText(profile[key], limit, defaults[key]);
  }
  normalized.age_stage = AGE_STAGES.has(profile.age_stage)
    ? profile.age_stage
    : defaults.age_stage;
  normalized.origin = ORIGINS.has(profile.origin) ? profile.origin : defaults.origin;
  return normalized;
}

export function encodeDaughterProfile(profile) {
  const normalized = normalizeDaughterProfile(profile);
  return bytesToBase64(utf8Encode(JSON.stringify(normalized)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

export function decodeDaughterProfile(value) {
  if (!value) return cloneDefaults();
  const parsed = JSON.parse(utf8Decode(base64ToBytes(value)));
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("女儿设定内容无效");
  }
  return normalizeDaughterProfile(parsed);
}

export function parseNixiRolepackPrompt(prompt) {
  if (typeof prompt !== "string") return null;
  const lines = prompt.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (!lines.length) return null;
  const match = NIXI_DIRECTIVE_RE.exec(lines[0]);
  if (!match) return null;

  const options = {};
  const optionOrder = [];
  const comments = [];
  for (const line of lines.slice(1)) {
    if (line.startsWith("#")) {
      comments.push(line);
      continue;
    }
    const separator = line.indexOf("=");
    if (separator <= 0) {
      return { mode: match[1], options, optionOrder, comments, invalidLine: line };
    }
    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim();
    if (!Object.prototype.hasOwnProperty.call(options, key)) optionOrder.push(key);
    options[key] = value;
  }
  return { mode: match[1], options, optionOrder, comments, invalidLine: null };
}

export function getDaughterEditorState(prompt) {
  const directive = parseNixiRolepackPrompt(prompt);
  if (!directive) return null;
  let profile = cloneDefaults();
  let error = directive.invalidLine ? `角色包选项格式错误：${directive.invalidLine}` : "";
  if (directive.options[PROFILE_OPTION]) {
    try {
      profile = decodeDaughterProfile(directive.options[PROFILE_OPTION]);
    } catch (decodeError) {
      error = decodeError.message || "女儿设定无法解析";
    }
  }
  return {
    mode: directive.mode,
    enabled: directive.options.audience === "daughter",
    profile,
    error
  };
}

export function updateDaughterSettings(prompt, enabled, profile) {
  const directive = parseNixiRolepackPrompt(prompt);
  if (!directive || directive.invalidLine) return prompt;
  const options = { ...directive.options };
  const order = [...directive.optionOrder];
  const ensureOrder = (key) => {
    if (!order.includes(key)) order.push(key);
  };

  if (enabled) {
    options.audience = "daughter";
    options[PROFILE_OPTION] = encodeDaughterProfile(profile);
    ensureOrder("audience");
    ensureOrder(PROFILE_OPTION);
  } else {
    delete options[PROFILE_OPTION];
    if (options.audience === "daughter") {
      options.audience = directive.mode === "duo" ? "observer" : "participant";
    }
    ensureOrder("audience");
  }

  const preferred = ["canon", "stage", "audience", "psychology", "voice", PROFILE_OPTION];
  const orderedKeys = [
    ...preferred.filter((key) => Object.prototype.hasOwnProperty.call(options, key)),
    ...order.filter((key) => !preferred.includes(key) && Object.prototype.hasOwnProperty.call(options, key))
  ];
  const uniqueKeys = [...new Set(orderedKeys)];
  return [
    `@rolepack nixi/${directive.mode}`,
    ...uniqueKeys.map((key) => `${key}=${options[key]}`),
    ...directive.comments
  ].join("\n");
}

