const CACHE='narcissus-public-shell-v1';
self.addEventListener('install',event=>{event.waitUntil(caches.open(CACHE).then(cache=>cache.add('/offline')).then(()=>self.skipWaiting()));});
self.addEventListener('activate',event=>{event.waitUntil(self.clients.claim());});
self.addEventListener('fetch',event=>{
 const url=new URL(event.request.url);if(event.request.method!=='GET'||url.origin!==self.location.origin||url.pathname.startsWith('/api/'))return;
 if(url.pathname.startsWith('/_next/static/')){event.respondWith(caches.open(CACHE).then(async cache=>{const saved=await cache.match(event.request);if(saved)return saved;const response=await fetch(event.request);if(response.ok)await cache.put(event.request,response.clone());return response;}));}
 else if(event.request.mode==='navigate'){event.respondWith(fetch(event.request).then(async response=>{if(response.ok&&url.pathname==='/offline')(await caches.open(CACHE)).put('/offline',response.clone());return response;}).catch(async()=>url.pathname==='/offline'?(await caches.match('/offline'))||new Response('离线页面尚未准备，请联网打开一次离线音频库。',{headers:{'Content-Type':'text/plain; charset=utf-8'}}):Response.redirect(new URL('/offline',self.location.origin).href)));}
});
