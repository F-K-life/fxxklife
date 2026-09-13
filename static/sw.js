/* Only per-account HTML shells and public assets are cached, never API data. */
const ASSETS='fs-assets-v9',META='fs-meta-v9',PAGES='fs-pages-v9-';let currentUser=null,changes=Promise.resolve();
self.addEventListener('install',e=>{self.skipWaiting();});
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
async function user(){if(currentUser!==null)return currentUser;const r=await(await caches.open(META)).match('/__fs_user');return currentUser=r?await r.text():'';}
async function purge(){currentUser='';await Promise.all((await caches.keys()).filter(k=>k.startsWith('fs-pages-')||k===META).map(k=>caches.delete(k)));}
self.addEventListener('message',e=>e.waitUntil(changes=changes.catch(()=>{}).then(async()=>{
 if(e.data?.type==='PURGE'){await purge();return;}
 if(e.data?.type==='AUTH'&&/^\d+$/.test(e.data.user)){const previous=await user();if(previous!==e.data.user)await purge();const uid=e.data.user;currentUser=uid;await(await caches.open(META)).put('/__fs_user',new Response(uid));
 const assets=await caches.open(ASSETS);await assets.addAll(['base','chat','focus','echoes','profile','liquid-glass'].map(n=>'/static/css/'+n+'.css').concat(['app','chat','focus','echoes','profile'].map(n=>'/static/js/'+n+'.js'),['/static/img/favicon.svg','/static/img/lighthouse-home.png']));
 const pageCache=await caches.open(PAGES+uid);for(const path of ['/chat','/focus','/echoes','/profile']){try{const response=await fetch(path,{credentials:'same-origin'});if(response.ok&&!response.redirected){const content=await response.clone().text();if(content.includes(`data-user-id="${uid}"`))await pageCache.put(path,response);}}catch{}}
 }
})));
self.addEventListener('fetch',e=>{
 const url=new URL(e.request.url);if(url.origin!==self.location.origin||e.request.method!=='GET')return;
 if(url.pathname.startsWith('/static/')){e.respondWith((async()=>{const cache=await caches.open(ASSETS);try{const r=await fetch(e.request);if(r.ok)await cache.put(e.request,r.clone());return r;}catch{return await cache.match(e.request)||Response.error();}})());return;}
 if(!['/chat','/focus','/echoes','/profile'].includes(url.pathname))return;
 e.respondWith((async()=>{try{return await fetch(e.request);}catch{const uid=await user();if(uid){const r=await(await caches.open(PAGES+uid)).match(url.pathname);if(r)return r;}return new Response('<!doctype html><meta charset="utf-8"><title>未来的我 · 等待连接</title><p>这页还未保存在设备上。恢复连接后重新打开，已保存的草稿与沉浸操作会继续同步。</p>',{status:503,headers:{'Content-Type':'text/html;charset=utf-8'}});}})());
});
