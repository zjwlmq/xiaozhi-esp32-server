// Keep example text out of saved credentials. A filled field is not proof of a successful API call.
export function isCredentialPlaceholder(value) {
  return typeof value === 'string' && /^(你的|请输入|请填写|your[_ -]|<your[_ -])/i.test(value.trim());
}

export function credentialState(value) {
  const text = String(value == null ? '' : value).trim();
  if (!text) return 'empty';
  if (isCredentialPlaceholder(text)) return 'placeholder';
  if (text.includes('****')) return 'masked';
  if (/[^\x21-\x7e]/.test(text)) return 'invalid';
  return 'filled';
}

export function normalizeCredential(value) {
  return isCredentialPlaceholder(value) ? '' : (value == null ? '' : value);
}

export function apiKeyInputType(field) {
  return field.prop === 'api_key' ? 'text' : (field.type || 'text');
}
