import { DEFAULT_VOICE_SETTINGS, VOICE_SETTINGS_KEY, getStoredVoiceSettings, normalizeVoiceSettings } from '../config/voice-settings.js?v=0907';

export class VoiceSettingsPanel {
    constructor(getHandler) {
        this.getHandler = getHandler;
        this.draft = getStoredVoiceSettings();
        this.pending = null;
        this.timer = null;
        this.applied = null;
        this.sequence = 0;
    }

    init() {
        this.panel = document.getElementById('voiceSettingsPanel');
        if (!this.panel) return;
        this.toggle = document.getElementById('voiceSettingsBtn');
        this.form = document.getElementById('voiceSettingsForm');
        this.status = document.getElementById('voiceSettingsStatus');
        this.controls = {
            version: document.getElementById('voiceVersion'),
            generation: document.getElementById('voiceGeneration'),
            language: document.getElementById('voiceLanguage'),
            speed: document.getElementById('voiceSpeed'),
            pitch: document.getElementById('voicePitch'),
        };
        this.toggle.addEventListener('click', () => this.setOpen(this.panel.hidden));
        document.getElementById('closeVoiceSettings').addEventListener('click', () => {
            this.setOpen(false);
            this.toggle.focus();
        });
        this.panel.addEventListener('keydown', event => {
            if (event.key === 'Escape') {
                this.setOpen(false);
                this.toggle.focus();
            }
        });
        this.form.addEventListener('submit', event => { event.preventDefault(); this.apply(); });
        document.getElementById('resetVoiceSettings').addEventListener('click', () => {
            this.draft = { ...DEFAULT_VOICE_SETTINGS };
            this.render();
            this.apply();
        });
        for (const [key, control] of Object.entries(this.controls)) {
            control.addEventListener('input', () => {
                this.draft[key] = ['speed', 'pitch'].includes(key) ? Number(control.value) : control.value;
                if (key === 'version') this.draft.generation = control.value === '1.0' ? 'trained' : 'standard';
                this.draft = normalizeVoiceSettings(this.draft);
                this.render();
                this.setStatus('参数已调整，点击“应用设置”生效。', 'pending');
            });
        }
        this.getHandler().onVoiceSettingsMessage = message => this.handleMessage(message);
        this.render();
        this.setOpen(!window.matchMedia('(max-width: 700px)').matches);
        this.setStatus('连接智能体后，可将声音设置应用到当前对话。');
    }

    setOpen(open) {
        this.panel.hidden = !open;
        this.toggle.setAttribute('aria-expanded', String(open));
    }

    render() {
        const following = this.draft.version === 'server';
        const legacy = this.draft.version === '1.0';
        for (const [key, control] of Object.entries(this.controls)) {
            control.value = this.draft[key];
            control.disabled = Boolean(this.pending) || (key !== 'version' && following);
        }
        for (const option of this.controls.generation.options) {
            option.hidden = option.value === 'trained' && !legacy;
            option.disabled = legacy ? option.value === 'expressive' : option.value === 'restoration';
        }
        document.getElementById('voiceSpeedValue').textContent = `${this.draft.speed.toFixed(1)}×`;
        document.getElementById('voicePitchValue').textContent = `${this.draft.pitch > 0 ? '+' : ''}${this.draft.pitch} 半音`;
        document.getElementById('voiceGenerationHint').textContent = following
            ? '使用智控台为当前智能体保存的声音参数。'
            : legacy ? this.draft.generation === 'trained'
                ? '使用当前已训练音色。标准版／还原版需先在服务端关联对应训练音色。'
                : '标准版／还原版使用各自已训练的音色，未关联时会提示配置。'
            : this.draft.generation === 'expressive'
                ? '表现力增强版支持更丰富的语气；可用性取决于音色训练版本。'
                : '2.0 标准版响应更快。还原版属于 1.0 的音色训练效果。';
        document.getElementById('applyVoiceSettings').disabled = Boolean(this.pending);
        document.getElementById('resetVoiceSettings').disabled = Boolean(this.pending);
    }

    setStatus(text, state = 'idle') {
        this.status.textContent = text;
        this.status.dataset.state = state;
    }

    persist(settings) {
        try { localStorage.setItem(VOICE_SETTINGS_KEY, JSON.stringify(settings)); }
        catch { this.setStatus('浏览器未能保存偏好；刷新或重连后请重新设置。', 'pending'); }
    }

    apply() {
        if (this.pending) return;
        const handler = this.getHandler();
        if (!handler.isConnected()) {
            this.setStatus('已保存，下次连接时应用。', 'saved');
            this.persist(this.draft);
            return;
        }
        if (!handler.voiceSettingsProtocol) {
            this.setStatus('当前服务端尚未支持声音设置，请更新服务端后重新连接。', 'error');
            return;
        }
        const requestId = `voice-${++this.sequence}`;
        this.pending = requestId;
        this.render();
        this.setStatus('正在应用声音设置…', 'pending');
        this.timer = setTimeout(() => {
            this.pending = null;
            this.render();
            this.setStatus('未收到服务端确认，请重连后再试。', 'error');
        }, 8000);
        if (!handler.sendVoiceSettings(this.draft, requestId)) {
            this.clearPending();
            this.setStatus('发送失败，请检查连接后重试。', 'error');
        }
    }

    clearPending() {
        clearTimeout(this.timer);
        this.timer = null;
        this.pending = null;
        this.render();
    }

    handleMessage(message) {
        if (!this.panel) return;
        if (message.status === 'disconnected') {
            this.clearPending();
            this.applied = null;
            this.setStatus('已断开；下次连接会重新应用已保存的声音设置。');
            return;
        }
        if (message.request_id && message.request_id !== this.pending) return;
        if (message.request_id) this.clearPending();
        if (message.status === 'accepted') {
            document.getElementById('voiceIdentity').textContent = message.voice
                ? `当前音色 · ${message.voice}` : '音色跟随当前绑定的智能体';
        }
        if (message.status === 'error') {
            this.setStatus(message.message || '声音设置未生效，请检查模型和音色。', 'error');
            return;
        }
        if (message.status === 'unsupported') {
            this.setStatus('服务端尚未支持声音设置；请更新服务端后重新连接。', 'error');
            return;
        }
        if (message.status === 'accepted' && message.settings) {
            this.applied = normalizeVoiceSettings(message.settings);
            const edited = Object.keys(DEFAULT_VOICE_SETTINGS).some(key => this.draft[key] !== this.applied[key]);
            this.setStatus(message.supported === false
                ? '当前智能体未使用火山复刻音色；可在智控台选择后重新连接。'
                : edited ? '已连接，面板参数尚未应用；点击“应用设置”确认。'
                    : this.applied.version === 'server' ? '正在使用智能体的声音设置。'
                        : '已应用，将用于下一次回复。', message.supported === false || edited ? 'pending' : 'applied');
            this.persist(this.applied);
        }
    }
}
