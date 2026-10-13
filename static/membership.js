const visibilityControl = document.getElementById('password-visibility-control');
const showPassword = document.getElementById('show-password');
if (visibilityControl && showPassword) {
    const passwordFields = ['password', 'password_confirm']
        .map(id => document.getElementById(id))
        .filter(Boolean);
    visibilityControl.hidden = false;
    showPassword.addEventListener('change', () => {
        for (const field of passwordFields) {
            field.type = showPassword.checked ? 'text' : 'password';
        }
    });
    // Restore masking when a browser restores this page from its history.
    window.addEventListener('pageshow', () => {
        showPassword.checked = false;
        for (const field of passwordFields) field.type = 'password';
    });
}
