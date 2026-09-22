(() => {
  const $=id=>document.getElementById(id),escape=FS.escape;
  const fields={ideal:'理想方向',current:'当下处境',values:'价值与边界',conditions:'行动条件',tone:'交流偏好'};
  const sourceNames={reflection:'行动反思',letter:'授权书信',onboarding:'首次自述',chat:'对话自述',profile:'手动画像',import:'授权资料',manual:'手动修正'};
  let state,editingMemory,busy=false,refreshVersion=0,history=[],materials=[],historyLoaded=false,viewingHistory,profileBase;
  let preferences,preferencesDirty=false,materialsVersion=0,importLinkOpened=false;
  let avatarDraft=FS.load('profile-avatar-style',{style:0,tone:0});
  const avatarSvg=(style=0,tone=0)=>{const colors=[['#a58aff','#33234f'],['#e6c78f','#553b2f'],['#91b8e8','#263e62'],['#d991ad','#592b49']][tone]||['#a58aff','#33234f'],gradient=`avatar-bg-${style}-${tone}`;const hair=[`<path d="M19 28c1-13 9-20 21-20s20 7 21 20c-8-7-14-9-21-9s-13 2-21 9Z"/>`,`<path d="M17 31c-3-14 5-25 23-25s26 11 23 25c-4-4-7-6-10-7-3-10-23-10-26 0-3 1-6 3-10 7Z"/><circle cx="18" cy="24" r="5"/><circle cx="62" cy="24" r="5"/>`,`<path d="M16 29c0-15 9-23 24-23s24 8 24 23v30H54V27c-8-9-20-9-28 0v32H16Z"/>`,`<path d="M17 27c5-13 12-19 23-19s18 6 23 19H17Z"/><path d="M13 27h54v7H13Z"/>`][style]||'';return `<svg viewBox="0 0 80 80" aria-hidden="true"><defs><linearGradient id="${gradient}" x1="0" y1="0" x2="1" y2="1"><stop stop-color="${colors[0]}"/><stop offset="1" stop-color="${colors[1]}"/></linearGradient></defs><rect width="80" height="80" rx="26" fill="url(#${gradient})"/><g fill="#17121f">${hair}</g><circle cx="40" cy="35" r="17" fill="#f1d7c2"/><path d="M24 33c4-10 10-15 18-15 7 0 13 4 16 11-10 1-17-2-22-6-2 6-6 9-12 10Z" fill="#17121f"/><circle cx="34" cy="36" r="1.4" fill="#332733"/><circle cx="46" cy="36" r="1.4" fill="#332733"/><path d="M36 44c3 2 5 2 8 0" fill="none" stroke="#9d5f66" stroke-linecap="round" stroke-width="1.5"/><path d="M17 75c2-15 11-23 23-23s21 8 23 23" fill="${colors[0]}" stroke="rgba(255,255,255,.45)"/></svg>`;};
  function paintAvatar(){const node=$('profile-avatar');if(node)node.innerHTML=avatarSvg(avatarDraft.style,avatarDraft.tone);document.querySelectorAll('[data-avatar-style]').forEach(b=>{b.innerHTML=avatarSvg(Number(b.dataset.avatarStyle),avatarDraft.tone);b.classList.toggle('active',Number(b.dataset.avatarStyle)===avatarDraft.style);});document.querySelectorAll('[data-avatar-tone]').forEach(b=>b.classList.toggle('active',Number(b.dataset.avatarTone)===avatarDraft.tone));}
  async function action(fn){if(busy)return;busy=true;try{await fn();}catch(error){FS.toast(error.message,'error');}finally{busy=false;}}
  async function refresh(){const version=++refreshVersion,result=await FS.state();if(version!==refreshVersion)return;state=result;preferences=result.preferences||preferences;render();}
  function sourceLink(ref,revoked=false){
    const id=encodeURIComponent(ref.source_id),type=ref.source_type;
    const href=type==='chat'?`/chat?message=${id}`:type==='import'?`/profile?import=${id}#import-section`:type==='letter'?`/echoes?letter=${id}`:type==='reflection'?`/echoes?event=${id}`:'/profile#self-definition';
    const text=`${sourceNames[type]||type} #${ref.source_id}${ref.revision?' · v'+ref.revision:''}`;
    return revoked?`<span>${escape(text)} · 已撤回</span>`:`<a href="${href}">${escape(text)} ↗</a>`;
  }
  function render(){
    const {user,profile,model}=state;
    $('profile-name').textContent=user.name;paintAvatar();
    $('account-badge').textContent=user.is_demo?'HACKATHON · 独立临时档案':'YOUR PERSONAL SPACE';
    $('profile-version').textContent=`画像版本 ${profile.version||1}`;$('profile-actions').textContent=state.events.length;
    $('profile-evidence').textContent=model.evidence_count||0;$('model-status').textContent=model.status||'还在了解你';
    Object.keys(fields).forEach(key=>$('profile-'+key).textContent=profile[key]||'尚未了解，等你愿意时慢慢说。');
    $('account-email').textContent=user.is_demo?`${user.name} · 黑客松临时账号`:user.email;
    $('account-type').textContent=user.is_demo?'这是独立的临时数据空间，不与其他体验者共用。':'正式账号 · 属于当前登录用户的数据空间';
    $('open-password').hidden=!!user.is_demo;$('delete-password-field').hidden=!!user.is_demo;$('delete-password').required=!user.is_demo;
    $('memory-switch').checked=!!user.memory_enabled;$('profile-reuse-switch').checked=!!user.profile_reuse_enabled;$('letters-switch').checked=!!user.auto_letters;
    $('model-mode').textContent=model.model?.label||'本地可解释建模';$('model-samples').textContent=model.evidence_count||0;
    $('model-minutes').textContent=model.rhythm?.recorded_minutes||0;$('model-suggested').textContent=model.rhythm?.suggested_minutes||10;
    $('model-basis').textContent=model.rhythm?.basis||'等待真实行动，逐步了解适合你的节奏。';
    const retrieval=model.retrieval||{};
    $('model-explanation-body').innerHTML=`<p><strong>两项独立授权</strong><br>建档复用决定五问画像是否跨登录参与个性化；长期记忆决定是否从授权记录学习和检索。你单独编辑的字段是明确的手动设定，不受建档复用开关影响。本次会话确认的答案也可临时使用。</p><p><strong>当前选择</strong><br>建档复用${user.profile_reuse_enabled?'已开启':'已关闭'}；长期记忆${user.memory_enabled?'已开启':'已关闭'}。只有授权、已确认且来源仍有效的记忆，才进入稳定理解。</p><p><strong>节奏建议</strong><br>${escape(model.rhythm?.basis||'暂无足够行动样本。')} · ${Number(model.rhythm?.sample_count||0)} 个可用样本。时长不等于注意力，也不是人格分数。</p><p><strong>检索方式</strong><br>${escape(retrieval.method||'依据相关性检索已确认信息')} · 每次最多 ${Number(retrieval.limit||6)} 条。</p>${(model.dimensions||[]).map(d=>`<div class="model-evidence"><strong>${escape(d.label||fields[d.key]||d.key)}</strong> · ${escape(d.value||'尚未了解')}<small>来源：${escape(d.source||'你的自述')}</small></div>`).join('')}${(retrieval.items||[]).map(item=>`<div class="model-evidence">${escape(item.content)}<small>${escape(item.reason||'已确认来源')}</small><div class="evidence-links">${sourceLink(item)}</div></div>`).join('')}`;
    $('import-learning-note').textContent=user.memory_enabled?'资料授权后会提出候选；只有你确认的理解才参与后续对话。':'长期记忆当前关闭。资料可以保存并单独授权，但当前不进行记忆学习。';
    renderGrowthMap();renderMemories();renderPreferences();renderConflicts();if(historyLoaded)renderHistory();
  }
  function renderGrowthMap(){
    const growth=state.growth||{},experiment=growth.active_experiment,capabilities=growth.capabilities||[],evidence=growth.recent_evidence||[],labels={unverified:'待验证',practicing:'练习中',evidenced:'已有证据'};
    $('growth-map-period').textContent=experiment?`第 ${growth.active_week?.week_number||experiment.current_week||1} 周`:'尚未建立主题';
    $('growth-map-identity').textContent=experiment?`${experiment.title} · ${experiment.future_identity}`:'从真实行动和你确认的证据中，慢慢看见变化。';
    $('growth-map-capabilities').innerHTML=capabilities.length?capabilities.map(capability=>{const sources=evidence.filter(item=>item.capability_id===capability.id);return `<article class="growth-capability-map"><div><h3>${escape(capability.name)}</h3><span class="growth-status ${escape(capability.status)}">${labels[capability.status]||'待验证'}</span></div><p>${escape(capability.target_state||'等待你定义目标状态')}</p><div class="growth-source-list">${sources.length?sources.map(item=>{const href=item.event_id?`/echoes?event=${encodeURIComponent(item.event_id)}`:item.task_id?`/focus?task=${encodeURIComponent(item.task_id)}`:'#';return `<a href="${href}">${escape(item.source_label||'成长证据')} ↗</a>`;}).join(''):'<span>还没有确认的作品或反思证据。</span>'}</div></article>`;}).join(''):'<p class="profile-empty-note">建立 12 周成长主题后，能力与证据会出现在这里。</p>';
  }
  function renderMemories(){
    const memories=state.memories.filter(item=>item.status!=='rejected');
    const pending=memories.filter(item=>['candidate','pending'].includes(item.status)).length;
    $('memory-count').textContent=pending?`${pending} 条待你确认`:`${memories.length} 条理解记录`;
    $('memory-list').innerHTML=memories.length?memories.map(item=>{
      const waiting=['candidate','pending'].includes(item.status),revoked=item.status==='revoked',confirmed=item.status==='confirmed';
      const status=revoked?'来源已撤回 · 不再采用':waiting?'待你确认':confirmed?(item.user_locked||item.kind==='correction'?'你已更正并锁定':'你已确认'):'待核对来源';
      const refs=Array.isArray(item.evidence_ids)&&item.evidence_ids.length?item.evidence_ids:[{source_type:item.source_type,source_id:item.source_id}];
      const conflicts=Array.isArray(item.conflicts_with)?item.conflicts_with:[];
      const comparison=conflicts.length?`<details class="memory-conflict"><summary>与 ${conflicts.length} 条手动修正待比较</summary>${conflicts.map(id=>{const old=state.memories.find(record=>String(record.id)===String(id));return `<p><strong>已锁定理解 #${escape(id)}</strong><br>${escape(old?.content||'请结合你目前的画像判断。')}</p>`;}).join('')}<small>确认候选不会自动覆盖这些手动设定。</small></details>`:'';
      return `<article class="memory-item" id="memory-${escape(item.id)}"><div class="memory-meta"><span class="memory-state ${waiting?'pending':revoked?'revoked':''}">${status}</span><time>${escape(FS.date(item.updated_at||item.created_at))}</time></div><span class="memory-field">${escape(fields[item.field]||'自我理解')} · ${escape(item.confidence||'由你确认')}</span><p>${escape(item.content||item.proposed_value)}</p>${item.reason?`<p class="memory-reason">理解依据：${escape(item.reason)}</p>`:''}${comparison}<div class="memory-source"><div class="evidence-links">${refs.map(ref=>sourceLink(ref,revoked)).join('')}</div><div class="memory-actions">${waiting?`<button type="button" class="confirm-memory" data-memory-action="confirm" data-id="${escape(item.id)}">确认是我</button>`:''}${!revoked?`<button type="button" data-memory-action="reject" data-id="${escape(item.id)}">不是我</button><button type="button" data-memory-action="edit" data-id="${escape(item.id)}" aria-label="修改这条记忆">${FS.icon('edit')}</button>`:''}<button type="button" data-memory-action="delete" data-id="${escape(item.id)}" aria-label="删除这条记忆">${FS.icon('trash')}</button></div></div></article>`;
    }).join(''):`<div class="memory-empty">${FS.icon('leaf')}<p>理解，会从真实的相处开始。</p><small>${state.user.memory_enabled?'对话、反思和授权资料带来的理解，会先等待你确认。':'长期记忆目前关闭。你仍然可以编辑画像、聊天与沉浸。'}</small></div>`;
  }
  function openProfile(values=state.profile,notice=''){
    profileBase={name:state.user.name,...Object.fromEntries(Object.keys(fields).map(key=>[key,state.profile[key]||'']))};
    $('edit-name').value=state.user.name;Object.keys(fields).forEach(key=>$('edit-'+key).value=values[key]||'');
    $('profile-edit-hint').textContent=notice||'你实际修改的字段将成为明确的手动设定，用于后续沟通与新来信；不改写过去的行动。';
    $('profile-dialog').showModal();
  }
  $('edit-profile').onclick=()=>{if(state)openProfile();};
  $('profile-avatar').onclick=$('customize-avatar').onclick=()=>{$('avatar-dialog').showModal();paintAvatar();};
  document.querySelectorAll('[data-avatar-style]').forEach(button=>button.onclick=()=>{avatarDraft={...avatarDraft,style:Number(button.dataset.avatarStyle)};paintAvatar();});
  document.querySelectorAll('[data-avatar-tone]').forEach(button=>button.onclick=()=>{avatarDraft={...avatarDraft,tone:Number(button.dataset.avatarTone)};paintAvatar();});
  $('save-avatar').onclick=()=>{FS.store('profile-avatar-style',avatarDraft);paintAvatar();$('avatar-dialog').close();FS.toast('小头像已保存在这个账号的浏览器中。');};
  $('profile-form').onsubmit=event=>{event.preventDefault();action(async()=>{
    const button=event.submitter||$('profile-form').querySelector('[type=submit]');button.disabled=true;
    try{
      const form=Object.fromEntries(new FormData($('profile-form'))),body=Object.fromEntries(Object.entries(form).filter(([key,value])=>value!==profileBase[key]));
      if(!Object.keys(body).length){$('profile-dialog').close();FS.toast('这份画像与当前版本一致。');return;}
      await FS.api('/api/profile',{method:'POST',body});$('profile-dialog').close();await refresh();if(historyLoaded)await loadHistory();FS.toast('已保存你明确修改的内容。');
    }finally{button.disabled=false;}
  });};
  document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>$(button.dataset.close).close());
  $('memory-list').onclick=event=>{
    const button=event.target.closest('[data-memory-action]');if(!button||busy)return;
    const operation=button.dataset.memoryAction,id=button.dataset.id,item=state.memories.find(record=>String(record.id)===id);
    if(operation==='edit'){editingMemory=item;$('memory-content').value=item.content;$('memory-dialog').showModal();return;}
    if(operation==='delete'&&!confirm('删除这条理解？原始来源会保留，这条记忆不再参与后续对话。'))return;
    if(operation==='confirm'&&item.conflicts_with?.length&&!confirm('这条候选与手动修正有待比较。确认保留这条候选？原有锁定内容不会被自动覆盖。'))return;
    action(async()=>{await FS.api('/api/memories/'+id,{method:operation==='delete'?'DELETE':'PATCH',body:{action:operation}});await refresh();FS.toast(operation==='confirm'?'这份理解已由你确认。':operation==='reject'?'已拒绝，仅保留防止重复出现的最小标记。':'这条理解已删除。');});
  };
  $('memory-form').onsubmit=event=>{event.preventDefault();action(async()=>{await FS.api('/api/memories/'+editingMemory.id,{method:'PATCH',body:{action:'edit',content:$('memory-content').value}});$('memory-dialog').close();await refresh();FS.toast('已以你的修正为准。');});};
  for(const [id,key]of [['memory-switch','memory_enabled'],['profile-reuse-switch','profile_reuse_enabled'],['letters-switch','auto_letters']])$(id).onchange=()=>{
    const control=$(id),value=control.checked;if(busy||!state){control.checked=Boolean(state?.user[key]);return;}
    action(async()=>{control.disabled=true;try{await FS.api('/api/profile',{method:'POST',body:{[key]:value}});await refresh();FS.toast(key==='profile_reuse_enabled'?(value?'建档画像已允许跨登录复用。':'已关闭建档复用；手动编辑字段仍生效。'):key==='memory_enabled'?(value?'长期学习已开启，候选仍需你确认。':'长期学习与记忆检索已关闭。'):(value?'自动来信已开启。':'自动来信已关闭。'));}catch(error){control.checked=!value;throw error;}finally{control.disabled=false;}});
  };
  async function loadHistory(){const result=await FS.api('/api/profile/history');history=Array.isArray(result.versions)?result.versions:[];historyLoaded=true;renderHistory();}
  function renderHistory(){
    $('history-list').innerHTML=history.length?history.map(version=>{
      const changes=Object.keys(fields).filter(key=>(version.snapshot?.[key]||'')!==(state.profile[key]||''));
      return `<article class="profile-record"><div><strong>画像 v${escape(version.version)}</strong><small>${escape(FS.date(version.created_at))} · ${changes.length?changes.length+' 项与现在不同':'与当前画像一致'}</small></div><div class="record-actions"><button type="button" data-history-action="view" data-id="${escape(version.id)}">查看对照</button><button type="button" data-history-action="restore" data-id="${escape(version.id)}">填入编辑</button><button type="button" data-history-action="delete" data-id="${escape(version.id)}" aria-label="删除这个历史版本">${FS.icon('trash')}</button></div></article>`;
    }).join(''):'<p class="profile-empty-note">暂无保留的历史快照。删除快照不会删除当前画像。</p>';
  }
  $('load-history').onclick=()=>{if(state)action(loadHistory);};
  function restoreVersion(version){if($('history-dialog').open)$('history-dialog').close();openProfile(version.snapshot,`已填入历史 v${version.version}。请逐项核对；点击保存后，实际变化的字段才作为新的手动版本生效。`);}
  $('history-list').onclick=event=>{
    const button=event.target.closest('[data-history-action]');if(!button)return;
    const version=history.find(item=>String(item.id)===button.dataset.id);if(!version)return;
    if(button.dataset.historyAction==='restore'){restoreVersion(version);return;}
    if(button.dataset.historyAction==='delete'){if(confirm(`删除历史 v${version.version} 的快照？当前画像不会改变，也不会自动恢复这份历史快照。`))action(async()=>{await FS.api('/api/profile/history/'+version.id,{method:'DELETE'});await loadHistory();FS.toast('这份历史快照已删除。');});return;}
    viewingHistory=version;$('history-dialog-title').textContent=`历史 v${version.version}，与此刻对照。`;
    $('history-detail').innerHTML=Object.entries(fields).map(([key,label])=>{const old=version.snapshot?.[key]||'',current=state.profile[key]||'';return `<section class="version-field ${old!==current?'changed':''}"><h3>${label}<span>${old===current?'未变化':'有变化'}</span></h3><div class="version-columns"><div><small>当时的自述</small><p>${escape(old||'尚未填写')}</p></div><div><small>当前画像</small><p>${escape(current||'尚未填写')}</p></div></div></section>`;}).join('');$('history-dialog').showModal();
  };
  $('restore-history').onclick=()=>{if(viewingHistory)restoreVersion(viewingHistory);};
  async function loadImports(){const revision=++materialsVersion,result=await FS.api('/api/imports');if(revision!==materialsVersion)return;materials=Array.isArray(result.imports)?result.imports:[];renderImports();}
  function renderImports(){
    $('import-count').textContent=`${materials.length} 份资料`;
    $('import-list').innerHTML=materials.length?materials.map(item=>`<article class="profile-record material-record"><div><strong>${escape(item.title)}</strong><small>${item.allow_memory?'已允许提出记忆候选':'仅保存 · 未授权学习'} · ${escape(FS.date(item.created_at))} · v${escape(item.revision||1)}</small><p>${escape(String(item.content||'').slice(0,100))}${String(item.content||'').length>100?'…':''}</p></div><div class="record-actions"><button type="button" data-import-action="preview" data-id="${escape(item.id)}">预览原文</button><button type="button" data-import-action="consent" data-id="${escape(item.id)}">${item.allow_memory?'撤回授权':'允许理解'}</button><button type="button" data-import-action="delete" data-id="${escape(item.id)}" aria-label="删除这份资料">${FS.icon('trash')}</button></div></article>`).join(''):'<p class="profile-empty-note">这里还没有导入资料。你可以只保存，而不授权学习。</p>';
    const linked=new URLSearchParams(location.search).get('import');if(linked&&!importLinkOpened){const item=materials.find(value=>String(value.id)===linked);if(item){importLinkOpened=true;previewMaterial(item);}}
  }
  function previewMaterial(item){$('import-preview-title').textContent=item.title;$('import-preview-content').textContent=item.content||'';$('import-preview-meta').textContent=`${item.allow_memory?'允许用于提出候选':'未授权学习'} · 资料 #${item.id} · v${item.revision||1}`;$('import-dialog').showModal();}
  function importMode(){const file=$('import-form').querySelector('[name=import_mode]:checked').value==='file';$('import-text-field').hidden=file;$('import-file-field').hidden=!file;$('import-content').required=!file;$('import-file').required=file;}
  document.querySelectorAll('[name=import_mode]').forEach(input=>input.onchange=importMode);
  $('import-content').oninput=()=>$('import-char-count').textContent=`${$('import-content').value.length} / 30000`;
  $('import-file').onchange=()=>{const file=$('import-file').files[0];if(!file)return;if(!$('import-title').value)$('import-title').value=file.name.slice(0,200);$('import-file-note').textContent=`${file.name} · ${(file.size/1024).toFixed(1)} KB，保存后可预览提取的正文。`;};
  $('import-form').onsubmit=event=>{event.preventDefault();action(async()=>{
    const button=event.submitter,mode=$('import-form').querySelector('[name=import_mode]:checked').value;let body;
    if(mode==='file'){const file=$('import-file').files[0];if(!file)throw new Error('请先选择一份资料。');if(file.size>512000)throw new Error('单份文件请控制在 500 KB 内。');if(!/\.(txt|md|csv|json|docx)$/i.test(file.name))throw new Error('请选择 TXT、MD、CSV、JSON 或 DOCX。');body=new FormData();body.set('file',file);body.set('title',$('import-title').value);body.set('allow_memory',String($('import-allow').checked));}
    else body={title:$('import-title').value,content:$('import-content').value,allow_memory:$('import-allow').checked};
    button.disabled=true;try{await FS.api('/api/imports',{method:'POST',body});$('import-form').reset();importMode();$('import-char-count').textContent='0 / 30000';$('import-compose').open=false;await loadImports();await refresh();FS.toast('资料已按你的授权选择保存。');}finally{button.disabled=false;}
  });};
  $('import-list').onclick=event=>{const button=event.target.closest('[data-import-action]');if(!button)return;const item=materials.find(value=>String(value.id)===button.dataset.id);if(!item)return;const operation=button.dataset.importAction;if(operation==='preview'){previewMaterial(item);return;}if(operation==='delete'&&!confirm('删除这份资料及关联记忆依据？已生成的历史内容可能需要另行清理。'))return;action(async()=>{await FS.api('/api/imports/'+item.id,{method:operation==='delete'?'DELETE':'PATCH',...(operation==='delete'?{}:{body:{allow_memory:!item.allow_memory}})});await loadImports();await refresh();FS.toast(operation==='delete'?'资料已删除。':item.allow_memory?'这份资料的学习授权已撤回。':'已允许从这份资料提出待确认观察。');});};
  function timezoneLabel(offset){const sign=offset>=0?'+':'−',value=Math.abs(offset);return `UTC${sign}${String(Math.floor(value/60)).padStart(2,'0')}:${String(value%60).padStart(2,'0')}`;}
  function renderPreferences(){
    if(!preferences)return;
    if(!preferencesDirty){$('weekly-enabled').checked=Boolean(preferences.weekly_enabled);$('weekly-day').value=preferences.weekly_day??6;$('weekly-hour').value=preferences.weekly_hour??20;}
    const offset=-new Date().getTimezoneOffset();$('preference-timezone').textContent=`已保存时区 ${timezoneLabel(Number(preferences.timezone_offset??offset))}；本次保存将使用当前设备时区 ${timezoneLabel(offset)}。`;
    const supported='Notification'in window,permission=supported?Notification.permission:'unsupported',enabled=Boolean(preferences.notifications_enabled)&&permission==='granted';
    $('enable-notifications').textContent=enabled?'关闭浏览器通知':'开启浏览器通知';$('notification-permission').textContent=enabled?'浏览器通知已开启；站内消息也会保留。':permission==='denied'?'浏览器未允许通知；站内提醒仍可查看。':!supported?'此浏览器使用站内提醒，不影响周回顾。':'未开启浏览器通知；点击右侧按钮后才会请求授权。';
  }
  async function loadPreferences(){const result=await FS.api('/api/preferences');preferences=result.preferences;renderPreferences();}
  $('preferences-form').oninput=()=>{preferencesDirty=true;};
  $('preferences-form').onsubmit=event=>{event.preventDefault();action(async()=>{const button=event.submitter;button.disabled=true;try{const result=await FS.api('/api/preferences',{method:'POST',body:{weekly_enabled:$('weekly-enabled').checked,weekly_day:Number($('weekly-day').value),weekly_hour:Number($('weekly-hour').value),timezone_offset:-new Date().getTimezoneOffset()}});preferences=result.preferences;preferencesDirty=false;renderPreferences();FS.toast('每周回顾的安排已保存。');}finally{button.disabled=false;}});};
  $('enable-notifications').onclick=async()=>{
    if(busy)return;if(!('Notification'in window)){FS.toast('当前浏览器使用站内提醒。');return;}
    const button=$('enable-notifications');button.disabled=true;busy=true;
    try{
      const disabling=Boolean(preferences?.notifications_enabled)&&Notification.permission==='granted';
      const permission=disabling?Notification.permission:Notification.permission==='granted'?'granted':await Notification.requestPermission();
      const result=await FS.api('/api/preferences',{method:'POST',body:{notifications_enabled:!disabling&&permission==='granted'}});preferences=result.preferences;renderPreferences();
      FS.toast(disabling?'浏览器提醒已关闭，站内消息保留。':permission==='granted'?'浏览器通知已开启。':'已保留站内提醒，不影响其他功能。');
    }catch(error){FS.toast(error.message,'error');}finally{button.disabled=false;busy=false;}
  };
  const draftNames={'chat-draft':'沟通草稿','letter-draft':'书信草稿','focus-task-draft':'沉浸任务草稿','action-draft':'行动建议草稿','onboarding-answers':'五问建档草稿'};
  function previewDraft(value){const text=typeof value==='string'?value:JSON.stringify(value,null,2);return text?text.slice(0,7000)+(text.length>7000?'\n…（预览已缩短，完整草稿仍保留）':''):'（空白草稿）';}
  function renderConflicts(){
    const conflicts=FS.load('draft-conflicts',{})||{},pending=Object.keys(FS.load('draft-outbox',{})||{}).length;
    $('draft-sync-note').textContent=`${navigator.onLine?'设备已联网':'当前离线，草稿留在本机'} · ${pending} 份草稿等待同步。不同版本由你选择，不自动覆盖。`;
    $('draft-conflict-list').innerHTML=Object.entries(conflicts).length?Object.entries(conflicts).map(([key,item])=>`<article class="draft-conflict"><h3>${escape(draftNames[key]||key)}</h3><div class="draft-choices"><section><small>这台设备的草稿</small><pre>${escape(previewDraft(item.local))}</pre><button type="button" class="button button-secondary compact-button" data-draft-key="${escape(key)}" data-draft-choice="local">保留本机版本</button></section><section><small>账号中的版本 · v${escape(item.remote?.version??0)}</small><pre>${escape(previewDraft(item.remote?.value))}</pre><button type="button" class="button button-secondary compact-button" data-draft-key="${escape(key)}" data-draft-choice="remote">使用账号版本</button></section></div></article>`).join(''):'<p class="profile-empty-note">目前没有需要你处理的草稿冲突。</p>';
  }
  $('draft-conflict-list').onclick=event=>{const button=event.target.closest('[data-draft-choice]');if(!button)return;action(async()=>{await FS.resolveDraft(button.dataset.draftKey,button.dataset.draftChoice);renderConflicts();FS.toast('已记录你的选择；联网后继续同步。');});};
  $('sync-drafts').onclick=()=>action(async()=>{await FS.syncNow();renderConflicts();FS.toast(navigator.onLine?'已检查同步状态。':'草稿留在本机，连接恢复后继续同步。');});
  $('open-password').onclick=()=>$('password-dialog').showModal();
  $('password-form').onsubmit=event=>{event.preventDefault();action(async()=>{await FS.api('/api/account/password',{method:'POST',body:Object.fromEntries(new FormData($('password-form')))});$('password-form').reset();$('password-dialog').close();FS.toast('登录密码已更新。');});};
  $('open-delete').onclick=()=>{$('delete-form').reset();$('delete-dialog').showModal();};
  $('delete-form').onsubmit=event=>{event.preventDefault();action(async()=>{event.submitter.disabled=true;try{await FS.api('/api/account',{method:'DELETE',body:{password:$('delete-password').value}});await FS.clearLocal();location.href='/login';}finally{event.submitter.disabled=false;}});};
  for(const name of ['fs:local','fs:draft','online','offline'])window.addEventListener(name,renderConflicts);
  window.addEventListener('fs:sync',()=>{renderConflicts();if(!busy){refresh().catch(()=>{});loadImports().catch(()=>{});if(historyLoaded)loadHistory().catch(()=>{});}});
  renderConflicts();refresh().catch(error=>FS.toast(error.message,'error'));
  loadImports().catch(error=>{$('import-list').textContent=error.message;});loadPreferences().catch(error=>FS.toast(error.message,'error'));
})();
