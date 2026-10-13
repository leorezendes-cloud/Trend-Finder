// Native details provides keyboard access and a working menu without JavaScript.
const siteMenu = document.getElementById('site-menu');
if (siteMenu) {
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && siteMenu.open) {
            siteMenu.open = false;
            siteMenu.querySelector('summary').focus();
        }
    });
    document.addEventListener('click', event => {
        if (siteMenu.open && !siteMenu.contains(event.target)) siteMenu.open = false;
    });
    window.addEventListener('pageshow', () => { siteMenu.open = false; });
}
