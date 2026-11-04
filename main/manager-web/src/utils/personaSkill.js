// Persona files become the current agent's system prompt, never executable code.
import { openPersonaZip, PersonaSkillError, SKILL_ARCHIVE_MAX_BYTES } from './personaSkillZip';

export { PersonaSkillError } from './personaSkillZip';
export const SYSTEM_PROMPT_MAX_BYTES = 65535;
export const SKILL_FILE_MAX_BYTES = 256 * 1024;

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

function readText(buffer, extension) {
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
  return { prompt, strippedFrontmatter, ...promptSize(prompt) };
}

const leaf = (name) => name.slice(name.lastIndexOf('/') + 1).toLowerCase();
const directory = (name) => name.slice(0, name.lastIndexOf('/') + 1).toLowerCase();
const normalized = (text) => text.replace(/\r\n/g, '\n').trim();

function readArchive(buffer) {
  const archive = openPersonaZip(buffer);
  const eligible = archive.entries.filter((entry) => !entry.name.split('/').some((part) => part.startsWith('.')
    || ['__macosx', '__pycache__', 'node_modules'].includes(part.toLowerCase())));
  const runtimeNames = ['full-system-prompt.txt', 'agent-patch.json'];
  const roots = [...new Set(eligible.filter((entry) => [...runtimeNames, 'skill.md'].includes(leaf(entry.name)))
    .map((entry) => directory(entry.name)))];
  // A top-level entry defines its package; nested source/versions are references.
  const packages = roots.filter((root) => !roots.some((other) => other !== root && root.startsWith(other)));
  if (packages.length !== 1) throw new PersonaSkillError(packages.length ? 'multiplePersonas' : 'missingSkill');
  const root = packages[0];
  const find = (name) => eligible.find((entry) => directory(entry.name) === root && leaf(entry.name) === name);
  const read = (entry) => readText(archive.read(entry, SKILL_FILE_MAX_BYTES), leaf(entry.name).split('.').pop());
  const readyText = find(runtimeNames[0]), readyJson = find(runtimeNames[1]), skill = find('skill.md');
  const usedFiles = [], verifiedFiles = [], alreadyIncludedFiles = [];
  let result;
  if (readyText || readyJson) {
    const chosen = readyText || readyJson;
    result = read(chosen);
    usedFiles.push(chosen.name);
    if (readyText && readyJson) {
      if (normalized(result.prompt) !== normalized(read(readyJson).prompt)) throw new PersonaSkillError('conflictingPrompts');
      verifiedFiles.push(readyJson.name);
    }
  } else {
    result = read(skill);
    usedFiles.push(skill.name);
    for (const name of ['persona.md', 'memories.md']) {
      const companion = find(name);
      if (!companion) continue;
      const addition = read(companion);
      if (normalized(result.prompt).includes(normalized(addition.prompt))) alreadyIncludedFiles.push(companion.name);
      else {
        result.prompt += `\n\n---\n\n# ${name}\n\n${addition.prompt}`;
        usedFiles.push(companion.name);
      }
    }
    const problem = systemPromptProblem(result.prompt, false);
    if (problem) throw new PersonaSkillError(problem);
    Object.assign(result, promptSize(result.prompt));
  }
  return { ...result, archive: true, strategy: readyText || readyJson ? 'prepared' : 'combined', usedFiles, verifiedFiles, alreadyIncludedFiles,
    ignoredFiles: archive.entries.length - usedFiles.length - verifiedFiles.length - alreadyIncludedFiles.length };
}

export async function readPersonaSkill(file) {
  const extension = /\.(md|txt|json|zip|skill)$/i.exec(file?.name || '')?.[1]?.toLowerCase();
  if (!extension) throw new PersonaSkillError('unsupportedFile');
  const archive = ['zip', 'skill'].includes(extension);
  const maxBytes = archive ? SKILL_ARCHIVE_MAX_BYTES : SKILL_FILE_MAX_BYTES;
  if (!file.size) throw new PersonaSkillError('empty');
  if (file.size > maxBytes) throw new PersonaSkillError(archive ? 'archiveTooLarge' : 'fileTooLarge');
  let buffer;
  try { buffer = await file.arrayBuffer(); }
  catch { throw new PersonaSkillError('readFailed'); }
  if (buffer.byteLength > maxBytes) throw new PersonaSkillError(archive ? 'archiveTooLarge' : 'fileTooLarge');
  const result = archive ? readArchive(buffer) : readText(buffer, extension);
  return { ...result, filename: file.name };
}
