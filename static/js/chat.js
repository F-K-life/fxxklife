(() => {
  const $ = selector => document.querySelector(selector);
  const messages=$('#messages'),input=$('#chat-input'),form=$('#chat-form'),send=$('#send-message'),dialog=$('#action-dialog'),actionForm=$('#action-form');
  let state=null,busy=false,suggestions=[],pending=FS.load('chat-pending'),initial=true,activeAction=null,listening=false,speaking=null,reloadPending=false,sourceTarget=new URLSearchParams(location.search).get('message'),sourceLocated=false;
  const seenActions=new Set();
  const actionObserver=new IntersectionObserver(entries=>{entries.forEach(entry=>{if(!entry.isIntersecting)return;const id=entry.target.dataset.actionSource;if(!seenActions.has(id)){seenActions.add(id);FS.track?.('action_card_viewed',id);}actionObserver.unobserve(entry.target);});},{root:$('#message-scroll'),threshold:.15});
  const feedbackLabels={direct:'更直接一点',listen:'先别给建议',correction:'这不是我'};
  const greeting=new Date().getHours();$('#greeting-time').textContent=greeting<6?'夜深了':greeting<11?'早上好':greeting<14?'中午好':greeting<18?'下午好':'晚上好';
  input.value=FS.load('chat-draft','');
  function resize(){input.style.height='auto';input.style.height=Math.min(input.scrollHeight,120)+'px';}
  function storeInput(){FS.store('chat-draft',input.value);resize();}
  input.addEventListener('input',storeInput);
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();form.requestSubmit();}});
  function modelLabel(model){return model?.label||'本地规则 · 演示模式';}
  function draftNotice(){$('#action-draft-notice').hidden=!FS.load('action-draft',null);}
  function card(suggestion,sourceId){
    const index=suggestions.push({...suggestion,source_message_id:sourceId})-1;
    const created=state?.tasks.find(t=>String(t.source_message_id)===String(sourceId));
    return `<div class="action-card" data-action-source="${sourceId}"><div class="action-card-top"><span>${FS.icon('leaf')} 一个可以开始的小行动</span><span>${FS.icon('clock')} ${FS.escape(suggestion.planned_minutes)} 分钟</span></div><h3>${FS.escape(suggestion.title)}</h3><p><b>第一步</b>${FS.escape(suggestion.first_step)}</p><p><b>做到这里</b>${FS.escape(suggestion.done_criteria)}</p><div class="action-card-footer">${created?`<a class="button button-secondary" href="/focus?task=${created.id}">查看已保存的行动 ${FS.icon('arrow-right')}</a><span class="action-already-saved">你已确认</span>`:`<button class="button button-primary open-action" data-index="${index}">进入沉浸 ${FS.icon('arrow-right')}</button><button class="text-link open-action" data-index="${index}">调整一下</button><button class="text-link dismiss-action" data-message-id="${sourceId}">暂时不做</button>`}</div></div>`;
  }
  function renderMessage(message){
    const user=message.role==='user',feedback=message.feedback||[],wrap=document.createElement('article');wrap.className=`message ${user?'user':'assistant'}`;if(message.id)wrap.dataset.messageId=message.id;
    wrap.innerHTML=`${user?'':'<span class="mini-orbit message-avatar" aria-hidden="true"></span>'}<div class="message-body"><div class="message-name">${user?'现在的我':'未来的我'}</div><div class="message-text">${FS.escape(message.content||message.reply_text)}</div>${!user&&message.action_suggestion&&!feedback.includes('dismiss_action')?card(message.action_suggestion,message.id):''}${!user&&message.model?`<div class="message-model-label">${FS.escape(modelLabel(message.model))}</div>`:''}${!user?`<div class="message-actions">${message.id?Object.entries(feedbackLabels).map(([key,label])=>`<button type="button" data-feedback="${key}" data-message-id="${message.id}" aria-pressed="${feedback.includes(key)}" class="${feedback.includes(key)?'feedback-applied':''}">${feedback.includes(key)?'✓ ':''}${label}</button>`).join(''):''}${'speechSynthesis' in window?`<button type="button" class="speak-message" aria-label="朗读这条回复">${FS.icon('play')}朗读</button>`:''}</div>`:''}</div>`;messages.append(wrap);const actionCard=wrap.querySelector('.action-card');if(actionCard)actionObserver.observe(actionCard);
  }
  function scroll(){const area=$('#message-scroll');area.scrollTop=area.scrollHeight;}
  function render(){
    const area=$('#message-scroll'),position=area.scrollTop,nearBottom=area.scrollHeight-area.clientHeight-position<50;actionObserver.disconnect();messages.innerHTML='';suggestions=[];
    if(!state.messages.length){const profile=state.model_profile||state.profile;renderMessage({role:'assistant',content:`嗨，${state.user.name}。很高兴在这里遇见你。\n\n${profile.ideal?`你说，你想「${profile.ideal}」。不用急着走到那里，我们可以先找到眼前的一小步。`:'关于想成为谁，我们可以慢慢聊。不用准备好一个完整的答案。'}\n\n今天，有什么想和我说说的吗？`});}else state.messages.forEach(renderMessage);
    $('#model-status').textContent=modelLabel(state.model?.model);$('#ideal-direction').textContent=(state.model_profile||state.profile).ideal||'还没想好，也没关系。方向可以一边走，一边找到。';$('#focus-invitation-text').textContent=state.active_session?'有一段未结束的沉浸，点击继续。':'留一小段时间，只做一件事。';
    if(state.user.is_demo&&initial){$('#model-status').textContent='独立体验账号 · '+modelLabel(state.model?.model);initial=false;}
    draftNotice();const source=sourceTarget?Array.from(messages.querySelectorAll('[data-message-id]')).find(el=>el.classList.contains('message')&&el.dataset.messageId===sourceTarget):null;if(source){source.classList.add('is-source-message');if(!sourceLocated){area.scrollTop+=source.getBoundingClientRect().top-area.getBoundingClientRect().top-16;sourceLocated=true;}else area.scrollTop=position;}else if(sourceTarget){area.scrollTop=position;if(!sourceLocated){sourceLocated=true;FS.toast('原消息不在当前载入的记录中。');}}else if(state.messages.length&&nearBottom)scroll();else area.scrollTop=position;
  }
  async function load(){try{state=await FS.state();if(sourceTarget&&!state.messages.some(m=>String(m.id)===sourceTarget)){try{const data=await FS.api('/api/messages/'+encodeURIComponent(sourceTarget));state.messages.unshift(data.message);}catch(error){FS.toast('这条来源记录未能载入，其他对话仍可继续。','error');sourceTarget=null;}}render();}catch(error){messages.innerHTML='<div class="empty-state">个人空间暂未加载。<button class="text-link" id="retry-load">再试一次</button></div>';$('#retry-load').onclick=load;FS.toast(error.message,'error');}}
  form.addEventListener('submit',async event=>{
    event.preventDefault();const text=input.value.trim();if(!text||busy)return;
    if(listening){FS.voice.stop();listening=false;}busy=true;send.disabled=true;$('#voice-input').disabled=true;input.readOnly=true;$('#typing').hidden=false;
    if(!pending||pending.message!==text)pending={message:text,request_id:crypto.randomUUID()};FS.store('chat-pending',pending);scroll();
    try{await FS.api('/api/chat',{method:'POST',body:pending});input.value='';FS.store('chat-draft','');FS.store('chat-pending',null);pending=null;sourceTarget=null;resize();await load();scroll();}
    catch(error){FS.toast(error.message,'error');}
    finally{busy=false;send.disabled=false;$('#voice-input').disabled=!FS.voice?.available;input.readOnly=false;$('#typing').hidden=true;input.focus();}
  });
  document.querySelectorAll('[data-prompt]').forEach(button=>button.addEventListener('click',()=>{input.value=button.dataset.prompt;storeInput();input.focus();}));
  function openAction(data){
    activeAction=String(data.source_message_id||'manual');const saved=FS.load('action-draft',null);const draft=saved&&String(saved.source_message_id||'manual')===activeAction?saved:data;
    for(const [key,value]of Object.entries(draft)){const field=actionForm.elements[key];if(field)field.value=value;}
    FS.store('action-draft',Object.fromEntries(new FormData(actionForm)));draftNotice();if(!dialog.open)dialog.showModal();
  }
  async function feedback(messageId,key,button){
    button.disabled=true;
    try{await FS.api(`/api/messages/${messageId}/feedback`,{method:'POST',body:{feedback:key}});const message=state.messages.find(m=>String(m.id)===String(messageId));if(message){message.feedback||=[];if(!message.feedback.includes(key))message.feedback.push(key);}render();FS.toast(key==='dismiss_action'?'这个提议已收起，重开页面也会记得你的选择。':key==='correction'?'已记下这次纠正。你也可以在画像页修正长期理解。':'已记下，后续对话会参考你的偏好。');}
    catch(error){FS.toast(error.message,'error');button.disabled=false;}
  }
  function resetSpeaking(){if(speaking){speaking.innerHTML=FS.icon('play')+'朗读';speaking.classList.remove('is-speaking');speaking=null;}}
  function stopSpeaking(){FS.voice?.stop();resetSpeaking();}
  messages.addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button)return;
    if(button.classList.contains('dismiss-action'))feedback(button.dataset.messageId,'dismiss_action',button);
    if(button.dataset.feedback)feedback(button.dataset.messageId,button.dataset.feedback,button);
    if(button.classList.contains('open-action'))openAction(suggestions[Number(button.dataset.index)]);
    if(button.classList.contains('speak-message')){
      if(speaking===button){stopSpeaking();return;}stopSpeaking();
      const text=button.closest('.message-body').querySelector('.message-text').textContent;speaking=button;button.innerHTML=FS.icon('pause')+'停止朗读';button.classList.add('is-speaking');FS.voice.speak(text,resetSpeaking);
    }
  });
  actionForm.addEventListener('input',()=>{if(!activeAction)return;FS.store('action-draft',Object.fromEntries(new FormData(actionForm)));$('#action-draft-status').textContent='调整已保存在当前设备。';draftNotice();});
  $('#resume-action-draft').onclick=()=>{const draft=FS.load('action-draft',null);if(draft)openAction(draft);};
  $('#discard-action-draft').onclick=()=>{FS.store('action-draft',null);draftNotice();FS.toast('小行动草稿已放下，对话仍然保留。');};
  $('#close-action').onclick=()=>dialog.close();
  actionForm.addEventListener('submit',async event=>{
    event.preventDefault();const data=Object.fromEntries(new FormData(event.target));data.planned_minutes=Number(data.planned_minutes);if(data.source_message_id)data.source_message_id=Number(data.source_message_id);else delete data.source_message_id;
    const button=event.submitter;button.disabled=true;
    try{const result=await FS.api('/api/tasks',{method:'POST',body:data});FS.store('action-draft',null);location.href='/focus?task='+result.task.id;}
    catch(error){FS.toast(error.message,'error');button.disabled=false;}
  });
  const clearDialog=$('#clear-dialog');$('#clear-chat').onclick=()=>clearDialog.showModal();$('#cancel-clear').onclick=()=>clearDialog.close();$('#confirm-clear').onclick=async event=>{const button=event.currentTarget;button.disabled=true;try{await FS.api('/api/messages',{method:'DELETE',body:{}});stopSpeaking();FS.store('chat-pending',null);pending=null;FS.store('action-draft',null);clearDialog.close();await load();FS.toast('这段对话已清空');}catch(error){FS.toast(error.message,'error');}finally{button.disabled=false;}};
  if(FS.voice?.available){
    $('#voice-input').onclick=async()=>{
      if(busy)return;
      const waveform=$('#voice-waveform'),live=$('#voice-live-text');
      if(listening){FS.voice.stop();listening=false;form.classList.remove('voice-active');waveform.hidden=true;$('#voice-input').classList.remove('recording');$('#voice-input').setAttribute('aria-label','开始语音输入');return;}
      let committed=input.value;const join=()=>committed+(committed?'\n':'');listening=true;form.classList.add('voice-active');waveform.hidden=false;$('#voice-input').classList.add('recording');$('#voice-input').setAttribute('aria-label','停止语音输入');$('#voice-status').hidden=false;$('#voice-status').textContent='实时转写只进入输入草稿，发送仍由你确认。';
      try{await FS.voice.listen(text=>{if(!busy){committed=(join()+text).slice(0,4000);input.value=committed;live.textContent=text||'正在听你说';storeInput();}},()=>{listening=false;form.classList.remove('voice-active');waveform.hidden=true;$('#voice-input').classList.remove('recording');$('#voice-input').setAttribute('aria-label','开始语音输入');if(!$('#voice-status').textContent||$('#voice-status').textContent==='实时转写只进入输入草稿，发送仍由你确认。')$('#voice-status').textContent='识别已停止。可以先修改文字，再决定发送。';},text=>{if(!busy){input.value=(join()+text).slice(0,4000);live.textContent=text||'正在听你说';resize();}},code=>{const messages={'no-speech':'没有听到清晰语音，请靠近麦克风后再试。','not-allowed':'麦克风权限被拒绝，请允许此页面使用麦克风。','service-not-allowed':'浏览器未允许语音识别服务，请在 Chrome 或 Safari 中重试。','audio-capture':'没有检测到可用麦克风，请检查系统输入设备。','network':'语音识别服务连接失败，请检查网络后再试。'};if(code!=='aborted')$('#voice-status').textContent=messages[code]||`语音识别暂未完成（${code}），可以再次尝试。`;});}
      catch(error){listening=false;form.classList.remove('voice-active');waveform.hidden=true;$('#voice-input').classList.remove('recording');$('#voice-input').setAttribute('aria-label','开始语音输入');FS.toast(error.message,'error');}
    };
  }else{$('#voice-input').disabled=true;$('#voice-input').setAttribute('aria-disabled','true');$('#voice-input').title='当前浏览器未提供语音识别，可继续键盘输入';$('#voice-status').hidden=false;$('#voice-status').textContent='当前浏览器未提供实时语音识别。请使用 Chrome 或 Safari，并允许麦克风权限；你仍可继续打字。';}
  window.addEventListener('pagehide',stopSpeaking);
  window.addEventListener('fs:draft',event=>{
    if(busy)return;const {key,value}=event.detail||{};
    if(key==='chat-draft'&&document.activeElement!==input){input.value=value||'';resize();}
    if(key==='action-draft'){draftNotice();if(value&&dialog.open&&!actionForm.contains(document.activeElement)){activeAction=String(value.source_message_id||'manual');for(const [name,content]of Object.entries(value)){if(actionForm.elements[name])actionForm.elements[name].value=content;}$('#action-draft-status').textContent='已同步另一设备的草稿。';}}
  });
  function syncView(){if(busy||dialog.open||document.hidden||document.activeElement===input||listening){reloadPending=true;return;}reloadPending=false;load();}
  window.addEventListener('fs:sync',syncView);
  input.addEventListener('blur',()=>{if(reloadPending)syncView();});
  dialog.addEventListener('close',()=>{if(reloadPending)syncView();});
  resize();draftNotice();load();
})();
