const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const handlers = {};
const stores = new Map();

function cache(name) {
  if (!stores.has(name)) stores.set(name, new Map());
  const entries = stores.get(name);
  return {
    async addAll() {},
    async match(key) { return entries.get(String(key)); },
    async put(key, value) { entries.set(String(key), value); },
  };
}

global.self = {
  addEventListener(type, handler) { handlers[type] = handler; },
  clients: { async claim() {} },
  skipWaiting() {},
  location: { origin: 'http://localhost:5004' },
};
global.caches = {
  async open(name) { return cache(name); },
  async keys() { return [...stores.keys()]; },
  async delete(name) { return stores.delete(name); },
};
global.fetch = async () => { throw new Error('offline'); };

async function dispatch(type, event = {}) {
  let pending;
  handlers[type]({
    ...event,
    waitUntil(promise) { pending = promise; },
    respondWith(promise) { pending = promise; },
  });
  return pending;
}

(async () => {
  await cache('fs-meta-v9').put('/__fs_user', new Response('7'));
  await cache('fs-pages-v9-7').put(
    '/chat',
    new Response('<h1>private cached conversation</h1>', { status: 200 })
  );

  const source = fs.readFileSync('static/sw.js', 'utf8');
  vm.runInThisContext(source, { filename: 'static/sw.js' });

  await dispatch('activate');
  assert.equal(
    (await caches.keys()).some(name => name.startsWith('fs-pages-') || name.startsWith('fs-meta-')),
    false,
    'activation must remove private page and identity caches from older workers'
  );

  const response = await dispatch('fetch', {
    request: { url: 'http://localhost:5004/chat', method: 'GET' },
  });
  assert.equal(response.status, 503);
  const html = await response.text();
  assert.match(html, /登录首页/);
  assert.match(html, /明日见 Self Echo/);
  const oldBrand = new RegExp('\\u672a\\u6765\\u7684\\u6211|Future\\u0020Self', 'i');
  assert.doesNotMatch(html, oldBrand);
  assert.doesNotMatch(html, /private cached conversation/);

  console.log('PASS: offline startup never restores a private page shell');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
