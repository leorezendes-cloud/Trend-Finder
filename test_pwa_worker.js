/* Verify that account pages and live results cannot enter the offline cache. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
(async () => {
 const listeners = {}, saved = [], deleted = [];
 const offline = {offline: true};
 let fail = false;
 const cache = {addAll: async assets => saved.push(...assets), match: async key => key === '/static/pwa/offline.html' ? offline : undefined};
 const context = {
  URL, Response,
  self: {location: {origin: 'https://trendfindah.com'}, addEventListener: (name, fn) => listeners[name] = fn, skipWaiting: async () => {}, clients: {claim: async () => {}}},
  caches: {open: async () => cache, keys: async () => ['unrelated-cache', 'trendfindah-offline-old'], delete: async name => deleted.push(name)},
  fetch: async () => {if (fail) throw Error('offline'); return {network: true};}
 };
 vm.runInNewContext(fs.readFileSync('static/pwa/service-worker.js', 'utf8'), context);
 let work;
 listeners.install({waitUntil: p => work = p}); await work;
 assert.deepEqual(saved, ['/static/pwa/offline.html', '/static/pwa/icon-192.svg', '/static/pwa/icon-512.svg']);
 listeners.activate({waitUntil: p => work = p}); await work;
 assert.deepEqual(deleted, ['trendfindah-offline-old']);
 const request = (path, method = 'GET', mode = 'cors') => {
  let response;
  listeners.fetch({request: {url: new URL(path, context.self.location.origin).href, method, mode}, respondWith: p => response = p});
  return response;
 };
 for (const path of ['/api/scores', '/login', '/password-reset?token=private', '/static/branding.css']) assert.equal(request(path), undefined);
 assert.equal(request('/login', 'POST', 'navigate'), undefined);
 assert.equal(request('https://other.example/'), undefined);
 assert.equal(request('/static/pwa/icon-192.svg?v=1'), undefined);
 assert.deepEqual(await request('/profile', 'GET', 'navigate'), {network: true});
 fail = true;
 assert.equal(await request('/profile', 'GET', 'navigate'), offline);
 assert.equal(saved.length, 3);
 console.log('PWA offline cache and live/account network checks passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});

/* Safari help stays actionable; other pages retain the browser's native prompt. */
(async () => {
 function setup(hasButton=true) {
  const listeners={}, clicks={}; let moved=false, focused=false;
  const button={hidden:false,addEventListener:(name,fn)=>clicks[name]=fn};
  const status={textContent:''};
  const steps={scrollIntoView:()=>{moved=true;},focus:()=>{focused=true;}};
  const window={matchMedia:()=>({matches:false}),addEventListener:(name,fn)=>listeners[name]=fn,isSecureContext:false};
  vm.runInNewContext(fs.readFileSync('static/pwa/install.js','utf8'),{window,navigator:{},document:{getElementById:id=>({'install-app-button':hasButton?button:null,'install-app-status':status,'installation-steps':steps}[id])}});
  return {listeners,clicks,button,status,moved:()=>moved&&focused};
 }
 const safari=setup();await safari.clicks.click();
 assert.match(safari.status.textContent,/Share button → Add to Home Screen/);
 assert.equal(safari.button.hidden,false);assert.equal(safari.moved(),true);
 let prevented=false;const home=setup(false);
 home.listeners.beforeinstallprompt({preventDefault:()=>{prevented=true;}});
 assert.equal(prevented,false);
 let prompted=false;const chrome=setup();
 chrome.listeners.beforeinstallprompt({preventDefault:()=>{},prompt:async()=>{prompted=true;},userChoice:Promise.resolve({outcome:'dismissed'})});
 await chrome.clicks.click();assert.equal(prompted,true);assert.equal(chrome.button.hidden,false);
 console.log('Safari installation help and native prompt checks passed.');
})();
