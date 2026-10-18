(() => {
    let installPrompt;
    const button = document.getElementById('install-app-button');
    const status = document.getElementById('install-app-status');
    const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
    if (standalone && status) status.textContent = 'You’re already using Trendfindah as an app.';
    window.addEventListener('beforeinstallprompt', event => {
        event.preventDefault();
        installPrompt = event;
        if (button && !standalone) button.hidden = false;
    });
    if (button) button.addEventListener('click', async () => {
        if (!installPrompt) return;
        button.disabled = true;
        try {
            await installPrompt.prompt();
            const choice = await installPrompt.userChoice;
            if (status) status.textContent = choice.outcome === 'accepted'
                ? 'Installation requested. Look for Trendfindah on your home screen.'
                : 'You can install later using your browser’s menu.';
        } catch (_) {
            if (status) status.textContent = 'Use the browser menu to add Trendfindah to your home screen.';
        } finally {
            installPrompt = null;
            button.hidden = true;
            button.disabled = false;
        }
    });
    window.addEventListener('appinstalled', () => {
        installPrompt = null;
        if (button) button.hidden = true;
        if (status) status.textContent = 'Trendfindah is installed. Open it from your home screen.';
    });
    if ('serviceWorker' in navigator && window.isSecureContext) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('/service-worker.js', {scope: '/', updateViaCache: 'none'})
                .catch(() => { /* The website and manual home-screen installation still work. */ });
        });
    }
})();
