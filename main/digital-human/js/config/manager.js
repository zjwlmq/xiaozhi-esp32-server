// 配置管理模块

// 默认唤醒词列表
export const DEFAULT_WAKE_WORDS = '你好小智\n你好小志\n小爱同学\n你好小鑫\n你好小新\n小美同学\n小龙小龙\n喵喵同学\n小滨小滨\n小冰小冰\n嘿你好呀';

const STANDALONE_RUNTIME_PORT = '8006';
const LOCAL_HOSTNAMES = new Set(['127.0.0.1', 'localhost', '::1', '[::1]']);

// python start.py 提供的本地运行时同时包含唤醒词桥；随智控台发布的
// /digital-human/ 只需要浏览器端麦克风和正式 OTA/WebSocket 链路。
export function isStandaloneRuntime(locationLike = window.location) {
    const hostname = String(locationLike?.hostname || '').toLowerCase();
    const port = String(locationLike?.port || '');
    return LOCAL_HOSTNAMES.has(hostname) && port === STANDALONE_RUNTIME_PORT;
}

export function getDefaultOtaUrl(locationLike = window.location) {
    if (isStandaloneRuntime(locationLike)) {
        return 'http://127.0.0.1:8002/xiaozhi/ota/';
    }

    const protocol = String(locationLike?.protocol || '');
    const origin = String(locationLike?.origin || '');
    if ((protocol === 'http:' || protocol === 'https:') && origin) {
        return new URL('/xiaozhi/ota/', origin).toString();
    }

    return 'http://127.0.0.1:8002/xiaozhi/ota/';
}

export function getDefaultWakewordEnabled(locationLike = window.location) {
    return isStandaloneRuntime(locationLike) ? 'true' : 'false';
}

export function getDefaultWakewordBridgeUrl(locationLike = window.location) {
    if (!isStandaloneRuntime(locationLike)) {
        return '';
    }

    const protocol = locationLike.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${locationLike.host}/wakeword-ws`;
}

// 生成随机MAC地址
function generateRandomMac() {
    const hexDigits = '0123456789ABCDEF';
    let mac = '';
    for (let i = 0; i < 6; i++) {
        if (i > 0) mac += ':';
        for (let j = 0; j < 2; j++) {
            mac += hexDigits.charAt(Math.floor(Math.random() * 16));
        }
    }
    return mac;
}

// 加载配置
export function loadConfig() {
    const deviceMacInput = document.getElementById('deviceMac');
    const deviceNameInput = document.getElementById('deviceName');
    const clientIdInput = document.getElementById('clientId');
    const otaUrlInput = document.getElementById('otaUrl');
    const wakewordWsUrlInput = document.getElementById('wakewordWsUrl');
    const wakewordEnabledInput = document.getElementById('wakewordEnabled');
    const wakewordListInput = document.getElementById('wakewordList');

    // 从localStorage加载MAC地址，如果没有则生成新的
    let savedMac = localStorage.getItem('xz_tester_deviceMac');
    if (!savedMac) {
        savedMac = generateRandomMac();
        localStorage.setItem('xz_tester_deviceMac', savedMac);
    }
    deviceMacInput.value = savedMac;

    // 从localStorage加载其他配置
    const savedDeviceName = localStorage.getItem('xz_tester_deviceName');
    if (savedDeviceName) {
        deviceNameInput.value = savedDeviceName;
    }

    const savedClientId = localStorage.getItem('xz_tester_clientId');
    if (savedClientId) {
        clientIdInput.value = savedClientId;
    }

    const savedOtaUrl = localStorage.getItem('xz_tester_otaUrl');
    otaUrlInput.value = savedOtaUrl || getDefaultOtaUrl();

    const savedWakewordWsUrl = localStorage.getItem('xz_tester_wakewordWsUrl');
    if (wakewordWsUrlInput) {
        wakewordWsUrlInput.value = savedWakewordWsUrl !== null
            ? savedWakewordWsUrl
            : getDefaultWakewordBridgeUrl();
    }

    const savedWakewordEnabled = localStorage.getItem('xz_tester_wakewordEnabled');
    if (wakewordEnabledInput) {
        wakewordEnabledInput.value = savedWakewordEnabled !== null
            ? savedWakewordEnabled
            : getDefaultWakewordEnabled();
    }

    const savedWakewordList = localStorage.getItem('xz_tester_wakewordList');
    if (savedWakewordList !== null && wakewordListInput) {
        wakewordListInput.value = savedWakewordList;
    } else if (wakewordListInput) {
        wakewordListInput.value = DEFAULT_WAKE_WORDS;
    }

    const emojiEnabledInput = document.getElementById('emojiEnabled');
    const savedEmojiEnabled = localStorage.getItem('xz_tester_emojiEnabled');
    if (savedEmojiEnabled !== null && emojiEnabledInput) {
        emojiEnabledInput.value = savedEmojiEnabled;
    }
}

// 保存配置
export function saveConfig() {
    const deviceMacInput = document.getElementById('deviceMac');
    const deviceNameInput = document.getElementById('deviceName');
    const clientIdInput = document.getElementById('clientId');
    const wakewordWsUrlInput = document.getElementById('wakewordWsUrl');
    const wakewordEnabledInput = document.getElementById('wakewordEnabled');
    const wakewordListInput = document.getElementById('wakewordList');

    localStorage.setItem('xz_tester_deviceMac', deviceMacInput.value);
    localStorage.setItem('xz_tester_deviceName', deviceNameInput.value);
    localStorage.setItem('xz_tester_clientId', clientIdInput.value);
    const emojiEnabledInput = document.getElementById('emojiEnabled');
    if (emojiEnabledInput) {
        localStorage.setItem('xz_tester_emojiEnabled', emojiEnabledInput.value);
    }
    if (wakewordEnabledInput) {
        localStorage.setItem('xz_tester_wakewordEnabled', wakewordEnabledInput.value);
    }
    if (wakewordListInput) {
        localStorage.setItem('xz_tester_wakewordList', wakewordListInput.value);
    }
    if (wakewordWsUrlInput && wakewordWsUrlInput.value.trim()) {
        localStorage.setItem('xz_tester_wakewordWsUrl', wakewordWsUrlInput.value.trim());
    }
}

// 获取配置值
export function getConfig() {
    // 从DOM获取值
    const deviceMac = document.getElementById('deviceMac')?.value.trim() || '';
    const deviceName = document.getElementById('deviceName')?.value.trim() || '';
    const clientId = document.getElementById('clientId')?.value.trim() || '';
    const emojiEnabled = document.getElementById('emojiEnabled')?.value !== 'false';

    return {
        deviceId: deviceMac,  // 使用MAC地址作为deviceId
        deviceName,
        deviceMac,
        clientId,
        emojiEnabled
    };
}

// 保存连接URL
export function saveConnectionUrls() {
    const otaUrl = document.getElementById('otaUrl').value.trim();
    const wsUrl = document.getElementById('serverUrl').value.trim();
    localStorage.setItem('xz_tester_otaUrl', otaUrl);
    localStorage.setItem('xz_tester_wsUrl', wsUrl);
}
