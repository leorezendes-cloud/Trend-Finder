# Phone installation

Trendfindah can be added to an iPhone or Android home screen. This is a web app; no app-store submission is needed. The existing website layout and account system are preserved.

After deployment, open Menu → Install app, or /install.

- iPhone/iPad: open in Safari, tap Share → Add to Home Screen. Enable Open as Web App if offered, then Add.
- Android: open in Chrome and use the Install Trendfindah button when available, or Chrome's Install app / Add to Home screen menu.

The app opens from the existing Trendfindah icon. A separate sign-in may be needed on first launch. Internet is required for scores, research, predictions and accounts. Push notifications and offline research are not included.

## Deployment handoff

Include app.py, pwa.py, templates/_branding_head.html, templates/_site_navigation.html, templates/install.html and the complete static/pwa directory. The release preparation script includes these files automatically. Serve /manifest.webmanifest and /service-worker.js directly, without authentication or redirects. The worker must remain at the origin root so it can control the app scope.

The service worker caches only the public offline message and two icons. It never stores account HTML, reset links, API responses, predictions or scores in Cache Storage. Navigations use the network and show the offline message only on a network failure. Existing browser HTTP caching policies remain in effect. Old app-owned offline caches are removed on activation; unrelated caches are preserved.

Checks: .venv/bin/python -m unittest test_pwa test_hosting test_page_layouts -q; node test_pwa_worker.js. Actual installation should also be checked on an iPhone and Android after deployment.
