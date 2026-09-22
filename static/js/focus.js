(() => {
  const $ = id => document.getElementById(id);
  const queueKey = 'focus-event-queue', snapshotKey = 'focus-snapshot', draftKey = 'focus-task-draft';
  let state, task, session, anchor = performance.now(), wallAnchor = Date.now(), serverAnchor = Date.now()/1000, hidden = FS.load('hide-timer', false), busy = false, syncing = null;
  let queue = FS.load(queueKey, []), sound = 'off', editingTask = null;
  const taskForm = $('task-form');
  const seconds = () => Math.max(0, Number(session?.elapsed_seconds || 0) + (session?.status === 'running' ? (performance.now() - anchor) / 1000 : 0));
  const serverNow = () => serverAnchor + (performance.now() - anchor)/1000;
  const clock = n => `${String(Math.floor(n / 60)).padStart(2, '0')}:${String(Math.floor(n % 60)).padStart(2, '0')}`;
  function persist() {
    FS.store(queueKey, queue);
    if (!state) return;
    const snapshot = {tasks:state.tasks || [],sessions:state.sessions || [],active_session:state.active_session,pending_ended:state.pending_ended || null,server_time:serverNow(),saved_at:Date.now()};
    if (session) snapshot[session.status === 'ended' ? 'pending_ended' : 'active_session'] = {...session,elapsed_seconds:seconds()};
    FS.store(snapshotKey, snapshot);
  }
  function restore() {
    const saved = FS.load(snapshotKey, null);
    if (!saved) return false;
    state = saved;
    const gap = (Date.now() - saved.saved_at) / 1000;
    state.server_time = Number(saved.server_time || saved.saved_at/1000) + Math.max(0,gap);
    if (state.active_session?.status === 'running') {
      state.active_session.elapsed_seconds = Number(state.active_session.elapsed_seconds || 0) + Math.max(0, gap);
      if (gap < 0 || gap > 86400) state.active_session.timing_review_required = true;
    }
    render();
    return true;
  }
  function paintTimer() {
    const planned = Number(session?.planned_minutes || task?.planned_minutes || 25) * 60, elapsed = seconds();
    $('timer').textContent = elapsed > planned ? `+${clock(elapsed - planned)}` : clock(Math.max(0, Math.ceil(planned - elapsed)));
    $('timer').hidden = hidden; $('timer-breath').hidden = !hidden;
    $('hide-time').textContent = hidden ? '显示数字' : '隐藏数字';
    $('timer-footer').textContent = session ? `已投入 ${clock(elapsed)}` : '属于你的一小段时光';
    $('timer-kicker').textContent = session?.status === 'ended' ? '这段时光，已留在本机' : elapsed >= planned && session ? '时间到了，也可以继续' : session?.status === 'paused' ? '休息一下，也很好' : '给自己一点时间';
  }
  function syncStatus(message) {
    $('focus-sync-bar').hidden = navigator.onLine && !queue.length && !message;
    $('focus-sync-message').textContent = message || (queue.length ? `${queue.length} 项操作已保存在此设备，等待按顺序同步。` : '当前离线。已载入的沉浸仍可暂停、继续和结束。');
    $('retry-focus-sync').disabled = !!syncing || !navigator.onLine;
    $('start-focus').disabled = busy || !!queue.length;
  }
  function render() {
    if (!state) return;
    state.tasks ||= []; state.sessions ||= [];
    session = state.active_session || (queue.length ? state.pending_ended : null);
    anchor = performance.now(); wallAnchor = Date.now(); serverAnchor = Number(state.server_time || Date.now()/1000);
    if (session) task = state.tasks.find(t => String(t.id) === String(session.task_id)) || session;
    else if (task) task = state.tasks.find(t => String(t.id) === String(task.id));
    if (!task) { const wanted = new URLSearchParams(location.search).get('task') || FS.load('selected-task', ''); task = state.tasks.find(t => String(t.id) === String(wanted)) || state.tasks.find(t => t.status !== 'completed'); }
    $('task-select').innerHTML = '<option value="">为自己设定一个小行动</option>' + state.tasks.map(t => `<option value="${FS.escape(t.id)}">${FS.escape(t.title)}</option>`).join('');
    document.body.classList.toggle('is-running', session?.status === 'running'); document.body.classList.toggle('is-paused', session?.status === 'paused');
    $('focus-mode').textContent = ({running:'此刻，只需在这里',paused:'暂停中 · 时间为你停留',ending:'计时已停止，等你留下回顾',ended:'回顾已保存在此设备'})[session?.status] || '准备好，再出发';
    $('focus-task-title').textContent = task?.title || '此刻，想专心做什么？';
    $('task-first-step').textContent = task?.first_step || '把大的愿望，拆成能开始的小事。';
    $('task-done').textContent = task?.done_criteria || '由你定义，怎样才算完成。';
    $('task-duration').textContent = `${task?.planned_minutes || 25} 分钟`;
    const growth=state.growth||{},week=growth.active_week,capabilities=growth.capabilities||[],capability=capabilities.find(item=>item.id===task?.capability_id);
    $('growth-focus-context').hidden=!task?.experiment_id;$('focus-capability').textContent=capability?.name||'待确认';$('focus-hypothesis').textContent=week?.hypothesis||'待确认本周假设';
    $('reflection-capability').innerHTML=capabilities.map(item=>`<option value="${FS.escape(item.id)}">${FS.escape(item.name)}</option>`).join('');if(task?.capability_id)$('reflection-capability').value=task.capability_id;
    $('start-focus').hidden = !!session;
    $('pause-focus').hidden = !['running','paused'].includes(session?.status); $('end-focus').hidden = $('pause-focus').hidden;
    $('continue-finish').hidden = session?.status !== 'ending';
    $('pause-focus').innerHTML = `${FS.icon(session?.status === 'paused' ? 'play' : 'pause')}<span>${session?.status === 'paused' ? '继续沉浸' : '暂停一下'}</span>`;
    $('task-select').disabled = !!session || !!queue.length; $('new-task').disabled = !!session || !!queue.length; $('adjust-focus-task').disabled = !task || !!session || !!queue.length; $('task-select').value = task?.id || '';
    const ended = state.sessions.filter(s => s.status === 'ended' && new Date(s.ended_at).toLocaleDateString() === new Date().toLocaleDateString());
    $('today-minutes').textContent = Math.floor(ended.reduce((sum,s) => sum + Number(s.elapsed_seconds || 0),0) / 60); $('today-sessions').textContent = ended.length;
    const review = session?.timing_review_required || ended.some(s => s.timing_review_required);
    $('timing-review-bar').hidden = !review;
    $('timing-review-link').href = `/echoes?session=${session?.id || ended.find(s => s.timing_review_required)?.id || ''}`;
    syncStatus(); paintTimer();
    if (session?.status === 'ending') showFinish();
  }
  async function refresh() {
    if (queue.length) { await synchronize(); return; }
    try { state = await FS.state(); render(); persist(); }
    catch (err) { if (!state && !restore()) throw err; syncStatus(navigator.onLine ? '服务暂未连通，当前记录在本机保留。' : '当前离线，已恢复上次保存的沉浸。'); }
  }
  async function synchronize() {
    if (syncing) return syncing;
    if (!navigator.onLine || !queue.length) { syncStatus(); return; }
    syncing = (async () => {
      while (queue.length) {
        const item = queue[0];
        try {
          await FS.api(`/api/focus/${item.session_id}`, {method:'POST',body:item.body});
          queue.shift(); persist();
        } catch (err) {
          item.body.offline = true; item.error = err.message; persist();
          syncStatus(`记录仍在本机：${err.message} 可再次同步。`);
          return;
        }
      }
      const fresh = await FS.state();
      if (!queue.length) { state = fresh; render(); persist(); FS.toast('记录已按顺序同步。'); }
    })();
    try { await syncing; } finally { syncing = null; syncStatus(queue[0]?.error ? `待同步：${queue[0].error}` : ''); if (queue.length && navigator.onLine && !queue[0].error) setTimeout(() => synchronize().catch(err => syncStatus(err.message)),0); }
  }
  async function changeSession(action, extra = {}) {
    if (!session) return;
    const elapsed = seconds(), now = Date.now(), occurred = serverNow(), id = session.id;
    const clockChanged = Math.abs((now - wallAnchor) - (performance.now() - anchor)) > 5000;
    const body = {action,...extra,request_id:crypto.randomUUID(),occurred_at:occurred,offline:!navigator.onLine || !!queue.length || clockChanged};
    queue.push({session_id:id,body});
    const next = {...session,elapsed_seconds:elapsed,status:({pause:'paused',resume:'running',end:'ending',finish:'ended'})[action],timing_review_required:!!session.timing_review_required || clockChanged};
    if (action === 'resume') next.running_since = occurred;
    if (action === 'end' || action === 'finish') next.ended_at = action === 'finish' && session.ended_at ? session.ended_at : new Date(occurred*1000).toISOString();
    if (action === 'finish') { Object.assign(next,extra); state.active_session = null; state.pending_ended = next; state.sessions = [next,...state.sessions.filter(s => s.id !== id)]; }
    else state.active_session = next;
    state.server_time = occurred; session = next; anchor = performance.now(); wallAnchor = now; serverAnchor = occurred; persist(); render();
    await synchronize();
  }
  async function operation(fn) {
    if (busy) return;
    busy = true; document.querySelectorAll('.focus-controls button,#confirm-end,#finish-form button[type=submit],#task-form button[type=submit]').forEach(b => b.disabled = true);
    try { await fn(); } catch (err) { FS.toast(err.message, 'error'); }
    finally { busy = false; document.querySelectorAll('.focus-controls button,#confirm-end,#finish-form button[type=submit],#task-form button[type=submit]').forEach(b => b.disabled = false); syncStatus(queue[0]?.error ? `待同步：${queue[0].error}` : ''); }
  }
  function showFinish() {
    if (!session) return;
    $('reflection-fact').textContent = `${session.title || task?.title || '这次沉浸'} · 记录了 ${clock(seconds())}`;
    if (!$('finish-dialog').open) { const saved = FS.load(`focus-result-${session.id}`, {}); if (saved.result) $('finish-form').elements.result.value = saved.result; $('focus-reflection').value = saved.reflection || ''; $('finish-dialog').showModal(); }
  }
  $('hide-time').onclick = () => { hidden = !hidden; FS.store('hide-timer', hidden); paintTimer(); };
  $('task-select').onchange = e => { task = state.tasks.find(t => String(t.id) === e.target.value); FS.store('selected-task', task?.id || ''); render(); };
  $('new-task').onclick = () => { editingTask=null;taskForm.reset();const saved=FS.load(draftKey,{}),draft=saved._task_id?{}:saved;for(const [key,value]of Object.entries(draft))if(taskForm.elements[key])taskForm.elements[key].value=value;$('task-dialog').showModal(); };
  $('adjust-focus-task').onclick=()=>{if(!task)return;editingTask=task.id;const saved=FS.load(draftKey,{}),draft=String(saved._task_id)===String(task.id)?saved:task;for(const [key,value]of Object.entries(draft))if(taskForm.elements[key])taskForm.elements[key].value=value;$('task-dialog').showModal();};
  taskForm.oninput = () => FS.store(draftKey, {...Object.fromEntries(new FormData(taskForm)),_task_id:editingTask});
  taskForm.onsubmit = e => { e.preventDefault(); operation(async () => { if (!navigator.onLine) { FS.toast('行动草稿已保留，连接恢复后再保存并开始。'); return; } const body = Object.fromEntries(new FormData(taskForm)); body.first_step=(body.first_step||body.title).trim();body.done_criteria=(body.done_criteria||`投入 ${body.planned_minutes||25} 分钟后，由我决定是否继续`).trim();body.planned_minutes = Number(body.planned_minutes); const data = await FS.api(editingTask?`/api/tasks/${editingTask}`:'/api/tasks', {method:editingTask?'PATCH':'POST',body}); task = data.task; FS.store('selected-task',task.id); FS.store(draftKey,{}); taskForm.reset(); $('task-dialog').close(); await refresh(); FS.toast('小行动已保存，由你决定何时开始。'); }); };
  $('start-focus').onclick = () => { if (!task) { $('new-task').click(); return; } operation(async () => { if (!navigator.onLine) { FS.toast('新沉浸需要先与服务器连接。已有沉浸可离线继续。'); return; } const pending = FS.load('focus-start-request',null); const body = pending?.task_id === task.id ? pending : {task_id:task.id,request_id:crypto.randomUUID()}; FS.store('focus-start-request',body); await FS.api('/api/focus/start',{method:'POST',body}); FS.store('focus-start-request',null); await refresh(); }); };
  $('pause-focus').onclick = () => operation(() => changeSession(session.status === 'paused' ? 'resume' : 'pause'));
  $('end-focus').onclick = () => $('end-dialog').showModal();
  $('confirm-end').onclick = () => operation(async () => { $('end-dialog').close(); await changeSession('end'); });
  $('continue-finish').onclick = showFinish;
  let helpLevel=0;$('focus-help').onclick=()=>{helpLevel=Math.min(3,helpLevel+1);const help=[`先问自己：现在最小的不确定是什么？`,task?.first_step||'只做一个两分钟能开始的动作。',`例如：${task?.first_step||'打开空白页，写下第一句。'}`][helpLevel-1];$('focus-help-content').hidden=false;$('focus-help-content').textContent=help;if(helpLevel===3)$('focus-help').disabled=true;};
  $('finish-form').oninput = () => { if (session) FS.store(`focus-result-${session.id}`,Object.fromEntries(new FormData($('finish-form')))); };
  $('finish-form').onsubmit = e => { e.preventDefault(); operation(async () => { const id = session.id, body = Object.fromEntries(new FormData($('finish-form'))); FS.store(`focus-result-${id}`,body); $('finish-dialog').close(); await changeSession('finish',body); if (!queue.length) { FS.store(`focus-result-${id}`,{});const saved=await submitGrowthEvidence(id,body);if(saved)location.href = `/echoes?session=${id}`; } else FS.toast('结果与反思已保存到此设备，连接恢复后自动同步。'); }); };
  async function submitGrowthEvidence(sessionId,body){
    if(!task?.experiment_id||(!body.evidence_content?.trim()&&!body.evidence_link?.trim()))return true;
    const event=state.events?.find(item=>String(item.session_id)===String(sessionId)),content=(body.evidence_link||body.evidence_content).trim();
    const draft={experiment_id:task.experiment_id,capability_id:Number(body.capability_id||task.capability_id),weekly_experiment_id:task.weekly_experiment_id,task_id:task.id,session_id:sessionId,event_id:event?.id,kind:body.evidence_link?'link':'reflection',content,source_label:task.title,confirmed_by_user:true,request_id:crypto.randomUUID()};FS.store('growth-evidence-draft',draft);
    try{await FS.api('/api/growth-evidence',{method:'POST',body:draft});FS.store('growth-evidence-draft',null);$('retry-evidence').hidden=true;return true;}catch(error){$('retry-evidence').hidden=false;$('finish-dialog').showModal();FS.toast(`沉浸结果已保存；成长证据待重试：${error.message}`,'error');return false;}
  }
  $('retry-evidence').onclick=()=>operation(async()=>{const draft=FS.load('growth-evidence-draft',null);if(!draft)return;await FS.api('/api/growth-evidence',{method:'POST',body:draft});FS.store('growth-evidence-draft',null);$('retry-evidence').hidden=true;location.href=`/echoes?session=${draft.session_id}`;});
  $('retry-focus-sync').onclick = () => operation(() => queue.length ? synchronize() : refresh());
  $('sound-volume').value = FS.load('focus-volume',0.25);
  document.querySelectorAll('[data-sound]').forEach(button => button.onclick = async () => { try { await FS.audio.set(button.dataset.sound,Number($('sound-volume').value)); sound = button.dataset.sound; document.querySelectorAll('[data-sound]').forEach(b => { b.classList.toggle('active',b === button); b.setAttribute('aria-pressed',String(b === button)); }); } catch (err) { FS.toast(err.message,'error'); } });
  $('sound-volume').oninput = async () => { const volume = Number($('sound-volume').value); FS.store('focus-volume',volume); if (sound !== 'off') try { await FS.audio.set(sound,volume); } catch (err) { FS.toast(err.message,'error'); } };
  document.querySelectorAll('[data-close]').forEach(b => b.onclick = () => $(b.dataset.close).close());
  window.addEventListener('online', () => { (queue.length ? synchronize() : refresh()).catch(err => syncStatus(err.message)); });
  window.addEventListener('offline', () => { persist(); syncStatus(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) persist(); else if (!busy) { restore(); (queue.length ? synchronize() : refresh()).catch(err => syncStatus(err.message)); } });
  window.addEventListener('pagehide',persist);
  window.addEventListener('fs:sync', () => { if (!busy && !syncing) (queue.length ? synchronize() : refresh()).catch(err => syncStatus(err.message)); });
  window.addEventListener('fs:local', () => { if (!busy && !syncing) { queue = FS.load(queueKey,[]); restore(); (queue.length ? synchronize() : refresh()).catch(err => syncStatus(err.message)); } });
  window.addEventListener('fs:draft', event => { if (event.detail?.key === draftKey && $('task-dialog').open && !taskForm.contains(document.activeElement)) { editingTask=event.detail.value?._task_id||null;for (const [name,value] of Object.entries(event.detail.value || {})) if (taskForm.elements[name]) taskForm.elements[name].value = value; } });
  setInterval(paintTimer,500);
  restore();
  (queue.length ? synchronize() : refresh()).catch(err => { $('focus-mode').textContent = '等待连接 · 本机记录会保留'; syncStatus(err.message); });
})();
