// Persona files become the current agent's system prompt, never executable code.
export const SYSTEM_PROMPT_MAX_BYTES = 65535;
export const SKILL_FILE_MAX_BYTES = 256 * 1024;

export class PersonaSkillError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

export function promptSize(text) {
  return {
    characters: Array.from(text || '').length,
    bytes: new TextEncoder().encode(text || '').length,
  };
}

export function systemPromptProblem(text, allowEmpty = true) {
  if (allowEmpty && text == null) return '';
  if (typeof text !== 'string' || text.includes('\0')) return 'invalidText';
  // JSON escapes can introduce an unpaired surrogate despite valid UTF-8 input.
  for (const character of text) {
    const point = character.codePointAt(0);
    if (point >= 0xd800 && point <= 0xdfff) return 'invalidText';
  }
  if (!allowEmpty && !text.trim()) return 'empty';
  if (promptSize(text).bytes > SYSTEM_PROMPT_MAX_BYTES) return 'tooLarge';
  return '';
}

export async function readPersonaSkill(file) {
  const extension = /\.(md|txt|json)$/i.exec(file?.name || '')?.[1]?.toLowerCase();
  if (!extension) throw new PersonaSkillError('unsupportedFile');
  if (!file.size) throw new PersonaSkillError('empty');
  if (file.size > SKILL_FILE_MAX_BYTES) throw new PersonaSkillError('fileTooLarge');

  let buffer;
  try {
    buffer = await file.arrayBuffer();
  } catch {
    throw new PersonaSkillError('readFailed');
  }
  // Recheck the actual length, including for callers other than a file input.
  if (buffer.byteLength > SKILL_FILE_MAX_BYTES) throw new PersonaSkillError('fileTooLarge');
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(buffer);
  } catch {
    throw new PersonaSkillError('invalidEncoding');
  }

  let prompt = text;
  let strippedFrontmatter = false;
  if (extension === 'json') {
    let document;
    try {
      document = JSON.parse(text);
    } catch {
      throw new PersonaSkillError('invalidJson');
    }
    if (!document || Array.isArray(document) || typeof document.systemPrompt !== 'string') {
      throw new PersonaSkillError('invalidJson');
    }
    // Other fields, including model IDs and memory, are intentionally ignored.
    prompt = document.systemPrompt;
  } else if (extension === 'md') {
    const frontmatter = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(text);
    if (frontmatter && /^(?:name|description)\s*:/m.test(frontmatter[1])) {
      prompt = text.slice(frontmatter[0].length);
      strippedFrontmatter = true;
    }
  }
  const problem = systemPromptProblem(prompt, false);
  if (problem) throw new PersonaSkillError(problem);
  return { prompt, filename: file.name, strippedFrontmatter, ...promptSize(prompt) };
}
