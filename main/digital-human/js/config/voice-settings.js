export const VOICE_SETTINGS_KEY = 'xz_tester_voice_settings_v1';
export const DEFAULT_VOICE_SETTINGS = Object.freeze({
    version: 'server', generation: 'standard', speed: 1, pitch: 0, language: 'zh-cn'
});

export function normalizeVoiceSettings(value) {
    const input = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    const settings = { ...DEFAULT_VOICE_SETTINGS };
    if (['server', '1.0', '2.0'].includes(input.version)) settings.version = input.version;
    const choices = settings.version === '1.0'
        ? ['trained', 'standard', 'restoration'] : ['standard', 'expressive'];
    settings.generation = choices.includes(input.generation) ? input.generation : choices[0];
    if (Number.isFinite(input.speed) && input.speed >= 0.5 && input.speed <= 2) settings.speed = input.speed;
    if (Number.isInteger(input.pitch) && input.pitch >= -12 && input.pitch <= 12) settings.pitch = input.pitch;
    if (['auto', 'zh-cn', 'en'].includes(input.language)) settings.language = input.language;
    return settings;
}

export function getStoredVoiceSettings(storage = localStorage) {
    try {
        return normalizeVoiceSettings(JSON.parse(storage.getItem(VOICE_SETTINGS_KEY)));
    } catch {
        return { ...DEFAULT_VOICE_SETTINGS };
    }
}
