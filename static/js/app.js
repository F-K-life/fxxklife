(() => {
 const user=document.body.dataset.userId,prefix=`future-self:${user}:`,draftKeys=new Set(['chat-draft','letter-draft','focus-task-draft','action-draft','onboarding-answers']);
 const save=(k,v)=>{try{localStorage.setItem(prefix+k,JSON.stringify(v));}catch{}};
 let draftTimer,syncing=false,lastRevision,notifications=[],audioContext,audioSource,audioGain;
 window.FS={
  async api(url,options={},retry=true){
   const init={...options,credentials:'same-origin',headers:{'X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content,...options.headers}};
   if(options.body&&!(options.body instanceof FormData)&&typeof options.body!=='string'){init.body=JSON.stringify(options.body);init.headers['Content-Type']='application/json';}
   let response;try{response=await fetch(url,init);}catch(cause){if(cause.name==='AbortError')throw cause;const e=new Error('连接暂时中断，输入已留在这台设备。');e.network=true;throw e;}
   const owner=response.headers.get('X-Future-Self-User');if(user!=='anonymous'&&owner&&owner!==user){await this.clearLocal();location.href='/login';throw new Error('登录账号已变化，请重新打开个人空间。');}
   const data=await response.json().catch(()=>({error:'服务暂未响应，请稍后重试。'}));
   if(!response.ok){
    if(response.status===403&&retry&&url!=='/api/session'){const session=await this.api('/api/session',{},false);if(String(session.user_id)!==user){location.href='/login';throw new Error('登录账号已变化，请重新打开个人空间。');}document.querySelector('meta[name="csrf-token"]').content=session.csrf_token;return this.api(url,options,false);}
    if(response.status===401){await this.clearLocal();location.href='/login';}const e=new Error(data.error||'操作未完成，请重试。');e.status=response.status;e.payload=data;throw e;
   }return data;
  },
  state(){return this.api('/api/state');},
  track(name,entity=''){if(user==='anonymous')return;this.api('/api/analytics',{method:'POST',body:{name,entity_id:String(entity),request_id:crypto.randomUUID()}}).catch(()=>{});},
  escape(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));},
  icon(n){return `<svg class="icon" aria-hidden="true"><use href="#i-${this.escape(n)}"></use></svg>`;},
  date(v){if(!v)return '';const d=new Date(v);return isNaN(d)?'':new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric'}).format(d);},
  store(k,v){save(k,v);const conflicts=this.load('draft-conflicts',{});if(conflicts[k]){conflicts[k].local=v;save('draft-conflicts',conflicts);}if(user!=='anonymous'&&draftKeys.has(k)){const out=this.load('draft-outbox',{}),versions=this.load('draft-versions',{});out[k]={value:v,base_version:out[k]?.base_version??versions[k]??0};save('draft-outbox',out);clearTimeout(draftTimer);draftTimer=setTimeout(()=>this.syncDrafts().catch(()=>{}),1000);}},
  load(k,fallback=null){try{return JSON.parse(localStorage.getItem(prefix+k))??fallback;}catch{return fallback;}},
  toast(message,type='info'){const el=document.createElement('div');el.className=`toast ${type==='error'?'error':''}`;el.textContent=message;document.querySelector('.toast-region').append(el);setTimeout(()=>el.remove(),4200);},
  async clearLocal(){Object.keys(localStorage).filter(k=>k.startsWith(prefix)).forEach(k=>localStorage.removeItem(k));navigator.serviceWorker?.controller?.postMessage({type:'PURGE'});if('caches'in window)await Promise.all((await caches.keys()).filter(k=>k.startsWith('fs-pages-')).map(k=>caches.delete(k)));},
  async syncDrafts(){
   if(syncing||user==='anonymous'||!navigator.onLine)return;syncing=true;
   try{const versions=this.load('draft-versions',{}),conflicts=this.load('draft-conflicts',{});
    for(const [k,pending]of Object.entries(this.load('draft-outbox',{}))){if(conflicts[k])continue;
     try{const result=await this.api('/api/drafts/'+k,{method:'PUT',body:pending});versions[k]=result.version;const latest=this.load('draft-outbox',{});if(JSON.stringify(latest[k])===JSON.stringify(pending))delete latest[k];else if(latest[k])latest[k].base_version=result.version;save('draft-outbox',latest);}
     catch(e){if(e.status===409){conflicts[k]={local:this.load(k),remote:e.payload.conflict||{value:null,version:0}};save('draft-conflicts',conflicts);this.toast('另一台设备有不同草稿，两份都保留在「画像 → 同步」。');}else throw e;}
    }
    const {drafts}=await this.api('/api/drafts'),out=this.load('draft-outbox',{});drafts.forEach(d=>{if(out[d.key]||conflicts[d.key])return;if(versions[d.key]!==d.version){const active=document.activeElement,forms={'chat-draft':'#chat-form','action-draft':'#action-form','focus-task-draft':'#task-form','letter-draft':'#letter-form'},editing=active?.closest?.(forms[d.key]||'#onboarding-form')||(d.key==='onboarding-answers'&&document.body.dataset.page==='onboarding'&&active?.matches?.('input,textarea'));if(editing&&JSON.stringify(this.load(d.key))!==JSON.stringify(d.value)){conflicts[d.key]={local:this.load(d.key),remote:d};save('draft-conflicts',conflicts);this.toast('另一台设备更新了正在编辑的草稿，两份内容已保留。');return;}save(d.key,d.value);window.dispatchEvent(new CustomEvent('fs:draft',{detail:{key:d.key,value:d.value}}));}versions[d.key]=d.version;});save('draft-versions',versions);
   }finally{syncing=false;}
  },
  async resolveDraft(key,choice){const conflicts=this.load('draft-conflicts',{}),c=conflicts[key];if(!c)return;const versions=this.load('draft-versions',{}),out=this.load('draft-outbox',{});versions[key]=c.remote.version;delete out[key];delete conflicts[key];save('draft-versions',versions);save('draft-outbox',out);save('draft-conflicts',conflicts);if(choice==='local')this.store(key,this.load(key,c.local));else{save(key,c.remote.value);window.dispatchEvent(new CustomEvent('fs:draft',{detail:{key,value:c.remote.value}}));}await this.syncDrafts();},
  audio:{async set(mode,volume=.3){
   if(mode==='off'){audioSource?.stop();audioSource=null;return;}
   const C=window.AudioContext||window.webkitAudioContext;if(!C){FS.toast('此浏览器未启用音频引擎。');return;}audioContext??=new C();await audioContext.resume();
   if(audioSource?.mode===mode){audioGain.gain.setTargetAtTime(volume,audioContext.currentTime,.1);return;}audioSource?.stop();const buffer=audioContext.createBuffer(1,audioContext.sampleRate*4,audioContext.sampleRate),samples=buffer.getChannelData(0);let previous=0;
   for(let i=0;i<samples.length;i++){const white=Math.random()*2-1;previous=(previous+.02*white)/1.02;samples[i]=mode==='brown'?previous*3.5:white*.4;}
   audioSource=audioContext.createBufferSource();audioSource.buffer=buffer;audioSource.loop=true;audioSource.mode=mode;const filter=audioContext.createBiquadFilter();filter.type=mode==='rain'?'highpass':'lowpass';filter.frequency.value=mode==='rain'?850:mode==='stream'?1500:400;audioGain=audioContext.createGain();audioGain.gain.value=0;audioSource.connect(filter).connect(audioGain).connect(audioContext.destination);audioSource.start();audioGain.gain.setTargetAtTime(volume,audioContext.currentTime,.2);
  }},
  voice:{available:!!(window.SpeechRecognition||window.webkitSpeechRecognition),recognition:null,
   async listen(onText,onEnd=()=>{},onInterim=()=>{},onError=()=>{}){
    if(this.recognition){this.recognition.stop();return;}
    if(!this.available){FS.toast('此浏览器未提供语音识别。文字输入与朗读仍可使用。');onEnd();return;}
    if(!FS.load('voice-consent')){const dialog=document.getElementById('voice-consent-dialog');const accepted=await new Promise(resolve=>{dialog.addEventListener('close',()=>resolve(dialog.returnValue==='allow'),{once:true});dialog.returnValue='';dialog.showModal();});if(!accepted){onEnd();return;}save('voice-consent',true);}
    const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition,r=this.recognition=new Recognition();r.lang='zh-CN';r.interimResults=true;r.continuous=true;r.onresult=e=>{let finalText='',interim='';for(let i=e.resultIndex;i<e.results.length;i++){const text=e.results[i][0].transcript;if(e.results[i].isFinal)finalText+=text;else interim+=text;}if(interim)onInterim(interim);if(finalText)onText(finalText);};r.onerror=e=>{const code=e.error||'unknown';onError(code);if(!['no-speech','aborted'].includes(code))FS.toast(code==='not-allowed'||code==='service-not-allowed'?'麦克风权限被拒绝，请允许此页面使用麦克风。':code==='audio-capture'?'没有检测到可用麦克风，请检查系统输入设备。':code==='network'?'语音识别服务连接失败，请检查网络后再试。':'语音识别暂未完成（'+code+'），可以再次尝试。');};r.onend=()=>{this.recognition=null;onEnd();};try{r.start();}catch(error){this.recognition=null;onError('start-failed');onEnd();}
   },
   speak(value,onEnd=()=>{}){if(!window.speechSynthesis){FS.toast('此浏览器未提供朗读引擎。');onEnd();return;}speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(value);u.lang='zh-CN';u.rate=.92;u.onend=onEnd;u.onerror=onEnd;speechSynthesis.speak(u);},
   stop(){this.recognition?.stop();window.speechSynthesis?.cancel();}
  },
  async notifications(){const result=await this.api('/api/notifications');notifications=result.notifications;const unread=notifications.filter(n=>!n.is_read),badge=document.querySelector('#notification-count');if(badge){badge.textContent=unread.length||'';badge.hidden=!unread.length;}const list=document.querySelector('#notification-list');if(list)list.innerHTML=notifications.length?notifications.map(n=>`<button class="notification-item ${n.is_read?'read':''}" data-notification="${n.id}"><span>${this.escape(n.title)}</span><p>${this.escape(n.body)}</p><small>${this.date(n.created_at)}</small></button>`).join(''):'<p class="empty-state">还没有新的来信提醒。时间会慢慢带来回响。</p>';
   if(result.preferences.notifications_enabled&&'Notification'in window&&Notification.permission==='granted'){const seen=new Set(this.load('notified',[]));unread.forEach(n=>{if(!seen.has(n.id)){const nfy=new Notification('未来的我',{body:n.title,tag:'future-self-'+n.id});nfy.onclick=()=>{window.focus();location.href=n.href;};seen.add(n.id);}});save('notified',[...seen].slice(-100));}return result;
  }
 };
 const reduced=FS.load('reduced-motion',matchMedia('(prefers-reduced-motion: reduce)').matches);document.documentElement.classList.toggle('reduced-motion',reduced);
 document.querySelector('.motion-toggle')?.addEventListener('click',e=>{const active=document.documentElement.classList.toggle('reduced-motion');FS.store('reduced-motion',active);e.currentTarget.setAttribute('aria-pressed',String(active));FS.toast(active?'已开启减少动效':'已恢复轻柔动效');});
 document.querySelectorAll('.live-date').forEach(el=>el.textContent=new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric',weekday:'long'}).format(new Date()));
 document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}}));
 const liquidTargets=document.querySelectorAll('.glass-card,.sidebar,.topbar,.chat-welcome,.future-postcard,.auth-form-panel,.question-card,.focus-sanctuary,.focus-sound,.identity-card,.echo-feature,.mailbox-section,.chat-composer,.quick-prompts button');
 liquidTargets.forEach(el=>{
  el.addEventListener('pointermove',event=>{const rect=el.getBoundingClientRect();if(!rect.width||!rect.height)return;el.style.setProperty('--liquid-x',`${((event.clientX-rect.left)/rect.width)*100}%`);el.style.setProperty('--liquid-y',`${((event.clientY-rect.top)/rect.height)*100}%`);},{passive:true});
  el.addEventListener('pointerleave',()=>{el.style.removeProperty('--liquid-x');el.style.removeProperty('--liquid-y');});
  el.addEventListener('pointerdown',()=>el.classList.add('liquid-pressed'),{passive:true});
  el.addEventListener('pointerup',()=>el.classList.remove('liquid-pressed'),{passive:true});
  el.addEventListener('pointercancel',()=>el.classList.remove('liquid-pressed'),{passive:true});
 });
 document.querySelectorAll('a[href^="/"]').forEach(link=>link.addEventListener('click',event=>{
  if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  const href=link.getAttribute('href');if(!href||href.startsWith('//')||href.startsWith('/api/'))return;
  document.body.classList.add('is-navigating');
 }));
 document.querySelector('#open-notifications')?.addEventListener('click',()=>{document.querySelector('#notification-dialog').showModal();FS.notifications().catch(e=>FS.toast(e.message,'error'));});document.querySelector('#close-notifications')?.addEventListener('click',()=>document.querySelector('#notification-dialog').close());
 document.querySelector('#notification-list')?.addEventListener('click',async e=>{const b=e.target.closest('[data-notification]');if(!b)return;const n=notifications.find(n=>n.id===Number(b.dataset.notification));try{await FS.api('/api/notifications/'+n.id,{method:'PATCH',body:{is_read:true}});location.href=n.href;}catch(e){FS.toast(e.message,'error');}});
 document.querySelector('form[action="/logout"]')?.addEventListener('submit',e=>{e.preventDefault();FS.clearLocal().finally(()=>e.target.submit());});if(user==='anonymous')return;
 FS.track('page_viewed',document.body.dataset.page);if(document.body.dataset.page==='onboarding')FS.track('onboarding_started');
 let polling=false;
 async function poll(){if(polling||document.hidden)return;polling=true;try{
  // The focus page owns its queue; other pages resume the same idempotent FIFO.
  if(document.body.dataset.page!=='focus'){for(const p of FS.load('focus-event-queue',[])){try{await FS.api('/api/focus/'+p.session_id,{method:'POST',body:p.body});save('focus-event-queue',FS.load('focus-event-queue',[]).filter(x=>x.body.request_id!==p.body.request_id));}catch(e){if(e.status&&e.status<500){const q=FS.load('focus-event-queue',[]),item=q.find(x=>x.body.request_id===p.body.request_id);if(item)item.error=e.message;save('focus-event-queue',q);}break;}}}
  await FS.syncDrafts();const sync=await FS.api('/api/sync'),label=document.querySelector('#sync-status');if(label){label.textContent='已同步';label.title='同账号设备共享记录；草稿冲突保留两份';}if(sync.revision!==lastRevision){lastRevision=sync.revision;window.dispatchEvent(new CustomEvent('fs:sync',{detail:sync}));await FS.notifications();}
 }catch{const label=document.querySelector('#sync-status');if(label)label.textContent='等待连接';}finally{polling=false;}}
 window.addEventListener('online',poll);window.addEventListener('storage',e=>{if(e.key?.startsWith(prefix))window.dispatchEvent(new CustomEvent('fs:local'));});document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});setInterval(poll,15000);setTimeout(poll,1200);FS.syncNow=poll;
 if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js').then(()=>navigator.serviceWorker.ready).then(reg=>reg.active.postMessage({type:'AUTH',user})).catch(()=>{});
 window.addEventListener('pagehide',()=>FS.voice.stop());
})();
