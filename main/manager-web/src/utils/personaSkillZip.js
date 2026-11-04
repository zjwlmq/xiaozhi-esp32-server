import { Inflate } from 'fflate';

export const SKILL_ARCHIVE_MAX_BYTES = 8 * 1024 * 1024;
export const SKILL_ARCHIVE_MAX_ENTRIES = 256;
const MAX_UNPACKED_BYTES = 16 * 1024 * 1024;

export class PersonaSkillError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

const fail = (code = 'invalidArchive') => { throw new PersonaSkillError(code); };

function pathName(bytes) {
  let name;
  try {
    name = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    fail();
  }
  name = name.replace(/\\/g, '/');
  const parts = name.replace(/\/$/, '').split('/');
  if (!name || name.startsWith('/') || /[\x00-\x1f:]/.test(name)
      || parts.some((part) => !part || part === '.' || part === '..')) fail();
  return name;
}

// Read ZIP32 metadata before allocating decompressed buffers. File data stays
// in memory; no archive path is ever opened or extracted onto a filesystem.
export function openPersonaZip(buffer) {
  const bytes = new Uint8Array(buffer);
  if (bytes.length < 22 || bytes.length > SKILL_ARCHIVE_MAX_BYTES) fail();
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const u16 = (at) => view.getUint16(at, true);
  const u32 = (at) => view.getUint32(at, true);
  let end = bytes.length - 22;
  for (; end >= Math.max(0, bytes.length - 65557); end -= 1) {
    if (u32(end) === 0x06054b50 && end + 22 + u16(end + 20) === bytes.length) break;
  }
  if (end < Math.max(0, bytes.length - 65557)) fail();
  const count = u16(end + 10), start = u32(end + 16), size = u32(end + 12);
  if (u16(end + 4) || u16(end + 6) || u16(end + 8) !== count
      || count === 0xffff || start === 0xffffffff || size === 0xffffffff) fail('unsupportedArchive');
  if (count > SKILL_ARCHIVE_MAX_ENTRIES) fail('archiveTooLarge');
  if (start + size !== end) fail();
  const entries = [], names = new Set(), ranges = [];
  let at = start, total = 0;
  for (let index = 0; index < count; index += 1) {
    if (at + 46 > end || u32(at) !== 0x02014b50) fail();
    const flags = u16(at + 8), method = u16(at + 10);
    const compressed = u32(at + 20), original = u32(at + 24), local = u32(at + 42);
    const nameSize = u16(at + 28), next = at + 46 + nameSize + u16(at + 30) + u16(at + 32);
    if (next > end || local + 30 > start || u16(at + 34)) fail();
    if (flags & 0x41 || ![0, 8].includes(method)
        || compressed === 0xffffffff || original === 0xffffffff) fail('unsupportedArchive');
    if (((u32(at + 38) >>> 16) & 0xf000) === 0xa000) fail('unsupportedArchive');
    const rawName = bytes.subarray(at + 46, at + 46 + nameSize);
    const name = pathName(rawName);
    const key = name.replace(/\/$/, '').toLowerCase();
    if (names.has(key)) fail();
    names.add(key);
    total += original;
    if (total > MAX_UNPACKED_BYTES) fail('archiveTooLarge');
    if (u32(local) !== 0x04034b50 || u16(local + 8) !== method || u16(local + 6) !== flags
        || u16(local + 26) !== nameSize) fail();
    const dataStart = local + 30 + nameSize + u16(local + 28);
    if (dataStart + compressed > start
        || !rawName.every((value, offset) => value === bytes[local + 30 + offset])) fail();
    if (!method && compressed !== original) fail();
    ranges.push([local, dataStart + compressed]);
    if (!name.endsWith('/')) entries.push({ name, method, compressed, original, dataStart, crc: u32(at + 16) });
    at = next;
  }
  if (at !== end) fail();
  ranges.sort((left, right) => left[0] - right[0]);
  if (ranges.some((range, index) => index && range[0] < ranges[index - 1][1])) fail();

  return {
    entries,
    read(entry, maxBytes) {
      if (!entries.includes(entry)) fail();
      if (entry.original > maxBytes) fail('fileTooLarge');
      const chunks = [];
      let length = 0, crc = -1;
      const collect = (chunk) => {
        length += chunk.length;
        if (length > maxBytes || length > entry.original) fail('fileTooLarge');
        for (const byte of chunk) {
          crc ^= byte;
          for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
        }
        chunks.push(chunk);
      };
      const data = bytes.subarray(entry.dataStart, entry.dataStart + entry.compressed);
      try {
        if (!entry.method) collect(data);
        else {
          const inflate = new Inflate(collect);
          // Bound actual output as well as declared size; stop forged-size ZIPs
          // before inflating the rest of a highly compressed entry.
          for (let offset = 0; offset < data.length; offset += 256) {
            inflate.push(data.subarray(offset, offset + 256), offset + 256 >= data.length);
          }
          if (!data.length) fail();
        }
      } catch (error) {
        if (error instanceof PersonaSkillError) throw error;
        fail();
      }
      if (length !== entry.original || ((crc ^ -1) >>> 0) !== entry.crc) fail();
      const result = new Uint8Array(length);
      let offset = 0;
      for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length; }
      return result;
    },
  };
}
