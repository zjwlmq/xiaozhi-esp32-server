export function safePluginImageUrl(value) {
    if (typeof value !== 'string' || value.length > 23 * 1024 * 1024) return null;
    if (/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}$/.test(value)) return value;
    try {
        const url = new URL(value);
        if (url.protocol === 'https:' && !url.username && !url.password) return url.href;
    } catch (_) { /* An invalid URL is not rendered. */ }
    return null;
}

export function appendPluginImage(message) {
    const stream = document.getElementById('chatStream');
    const url = safePluginImageUrl(message?.url);
    if (!stream || !url) return false;
    const row = document.createElement('div');
    row.className = 'chat-message ai';
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    const image = document.createElement('img');
    image.src = url;
    image.alt = '生成的图片';
    image.referrerPolicy = 'no-referrer';
    image.loading = 'lazy';
    image.style.cssText = 'display:block;max-width:min(100%,360px);max-height:480px;border-radius:10px;object-fit:contain';
    const caption = document.createElement('div');
    caption.textContent = '生成图片';
    caption.style.cssText = 'font-size:12px;opacity:.65;margin-top:8px';
    image.addEventListener('error', () => { caption.textContent = '图片暂时无法加载'; });
    image.addEventListener('load', () => { stream.scrollTop = stream.scrollHeight; });
    bubble.append(image, caption);
    row.appendChild(bubble);
    stream.appendChild(row);
    stream.scrollTop = stream.scrollHeight;
    return true;
}
