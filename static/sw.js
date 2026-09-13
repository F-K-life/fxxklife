/* Cache public assets only. Authenticated HTML and identity never go offline. */
const ASSETS='fs-assets-v10';let changes=Promise.resolve();
self.addEventListener('install',e=>{self.skipWaiting();});
self.addEventListener('activate',e=>e.waitUntil((async()=>{await Promise.all((await caches.keys()).filter(k=>(k.startsWith('fs-pages-')||k.startsWith('fs-meta-')||(k.startsWith('fs-assets-')&&k!==ASSETS))).map(k=>caches.delete(k)));await self.clients.claim();})()));
async function purge(){await Promise.all((await caches.keys()).filter(k=>k.startsWith('fs-pages-')||k.startsWith('fs-meta-')).map(k=>caches.delete(k)));}
self.addEventListener('message',e=>e.waitUntil(changes=changes.catch(()=>{}).then(async()=>{
 if(e.data?.type==='PURGE'){await purge();return;}
 if(e.data?.type==='AUTH'&&/^\d+$/.test(e.data.user)){await purge();
 const assets=await caches.open(ASSETS);await assets.addAll(['base','chat','focus','echoes','profile','liquid-glass'].map(n=>'/static/css/'+n+'.css').concat(['app','chat','focus','echoes','profile'].map(n=>'/static/js/'+n+'.js'),['/static/img/favicon.svg','/static/img/lighthouse-home.png']));
 }
})));
self.addEventListener('fetch',e=>{
 const url=new URL(e.request.url);if(url.origin!==self.location.origin||e.request.method!=='GET')return;
 if(url.pathname.startsWith('/static/')){e.respondWith((async()=>{const cache=await caches.open(ASSETS);try{const r=await fetch(e.request);if(r.ok)await cache.put(e.request,r.clone());return r;}catch{return await cache.match(e.request)||Response.error();}})());return;}
 if(!['/chat','/focus','/echoes','/profile'].includes(url.pathname))return;
 e.respondWith((async()=>{try{return await fetch(e.request);}catch{return new Response('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>明日见 Self Echo · 等待连接</title><main><h1>应用尚未连接</h1><p>请先启动服务，然后返回登录首页。</p><p><a href="/login">返回登录首页</a></p></main>',{status:503,headers:{'Content-Type':'text/html;charset=utf-8','Cache-Control':'no-store'}});}})());
});
