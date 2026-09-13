(() => {
  const $ = id => document.getElementById(id), escape = FS.escape;
  let state, goals = [], history = new Map(), cursor = null, hasMore = false, historyReady = false, tab = 'received', selectedLetter, selectedMilestone, selectedEvent, editingGoal = null, editingMilestone = null, decomposingGoal, steps = [], busy = false, refreshing = false, refreshPending = false, selectedReview = null;
  const viewedEvents=new Set(),viewedLetters=new Set();
  const results = {completed:'完成了',partial:'推进了一些',stopped:'今天先到这里'};
  const shortDate = value => value ? new Date(value.length === 10 ? `${value}T12:00:00` : value).toLocaleDateString('zh-CN',{month:'long',day:'numeric'}) : '日期未设定';
  const fullDate = value => value ? new Date(value).toLocaleString('zh-CN',{year:'numeric',month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
  const events = () => [...history.values()].sort((a,b) => new Date(a.created_at) - new Date(b.created_at));
  function open(id) { if (!$(id).open) $(id).showModal(); }
  async function action(fn, button) { if (busy) return; busy = true; if (button) button.disabled = true; try { await fn(); } catch(err) { FS.toast(err.message,'error'); } finally { busy = false; if (button) button.disabled = false; } }
  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
      const [fresh,page,goalData] = await Promise.all([FS.state(),FS.api('/api/events?limit=30'),FS.api('/api/goals')]);
      state = fresh; goals = goalData.goals || [];
      (page.events || []).forEach(e => history.set(String(e.id),e));
      if (!historyReady) { cursor = page.next_cursor; hasMore = page.has_more; historyReady = true; }
      for (const item of state.events || []) if (history.has(String(item.id))) history.set(String(item.id),item);
      render();
    } finally { refreshing = false; }
  }
  async function loadMore() {
    const page = await FS.api(`/api/events?limit=30${cursor ? '&before=' + encodeURIComponent(cursor) : ''}`);
    (page.events || []).forEach(e => history.set(String(e.id),e)); cursor = page.next_cursor; hasMore = page.has_more; render();
  }
  function render() {
    const list = events(), milestones = state.milestones || [];
    $('timeline-track').innerHTML = list.map(e => `<button type="button" class="timeline-node" data-event="${e.id}"><span class="node-date">${escape(shortDate(e.created_at))}</span><span class="node-mark">${FS.icon('leaf')}</span><span class="node-title">${escape(e.title)}</span><span class="node-sub">${results[e.result] || '真实记录'} · ${Math.floor(e.elapsed_seconds / 60)} 分钟${e.timing_review_required ? ' · 待校正' : ''}</span></button>`).join('') + `<button type="button" class="timeline-node today" id="today-node"><span class="node-date">${shortDate(new Date().toISOString())} · 今天</span><span class="node-mark">${FS.icon('spark')}</span><span class="node-title">你正在这里</span><span class="node-sub">每一步，都算数</span></button>` + milestones.map(m => `<button type="button" class="timeline-node ${m.completed ? '' : 'future'}" data-milestone="${m.id}"><span class="node-date">${escape(shortDate(m.date))}</span><span class="node-mark">${m.completed ? FS.icon('check') : ''}</span><span class="node-title">${escape(m.title)}</span><span class="node-sub">${m.completed ? '你已确认完成' : '未来计划 · 尚未完成'}</span></button>`).join('');
    $('load-more-events').hidden = !hasMore; $('history-count').textContent = `已展开 ${history.size} 条真实行动${hasMore ? ' · 更早的故事仍在' : ''}`;
    $('milestone-progress').textContent = milestones.length ? `已确认完成 ${milestones.filter(m => m.completed).length} / ${milestones.length} 个计划` : '每一个开始，都值得被看见。';
    $('today-node').onclick = () => { const found = list.filter(e => new Date(e.created_at).toLocaleDateString() === new Date().toLocaleDateString()).pop(); if (found) showEvent(found.id); else { $('event-label').textContent = 'RIGHT HERE, RIGHT NOW'; $('event-title').textContent = '今天，还可以从一小步开始。'; $('complete-milestone').hidden = true; $('event-details').innerHTML = `<p class="event-reflection">今天还没有保存的沉浸记录。休息、聊天，或为自己留出片刻，都可以由你选择。</p><a class="button button-primary" href="/focus">给自己一点时间${FS.icon('arrow-right')}</a>`; open('event-dialog'); } };
    renderMail();renderGoals();
  }
  function renderMail() {
    ['received','sent'].forEach(direction => $(direction+'-count').textContent = state.letters.filter(l => l.direction === direction).length);
    const pending = (state.events || []).filter(e => ['pending','queued','running'].includes(e.letter_status));
    const card = l => `<button type="button" class="letter-card ${l.locked ? 'locked-letter' : !l.is_read && l.direction === 'received' ? 'unread' : ''}" data-letter="${l.id}"><div class="letter-card-top">${FS.icon(l.locked ? 'shield':'mail')}<span>${escape(shortDate(l.open_at && l.locked ? l.open_at:l.created_at))}</span></div>${!l.locked && !l.is_read && l.direction === 'received' ? '<i class="unread-dot" aria-label="未读"></i>' : ''}<h3>${escape(l.title)}</h3><p class="letter-preview">${l.locked ? '封存中。留给约定日期的自己。' : escape(l.body)}</p><div class="letter-card-foot"><span>${l.locked ? '将在 ' + escape(fullDate(l.open_at)) + ' 开启' : l.source_adjusted ? '依据已调整 · 可查看原信或确认重写' : l.direction === 'received' ? 'FROM YOUR IDEAL SELF · 理想自我视角' : 'TO THE YOU AHEAD · 来自此刻的你'}</span>${FS.icon(l.locked?'clock':'arrow-right')}</div></button>`;
    const empty = direction => `<div class="mail-empty">${FS.icon('mail')}<h3>${direction === 'received' ? '让一份真实的行动，成为来信的起点。' : '此刻的你，有什么想对未来说？'}</h3><p>${direction === 'received' ? '一次沉浸后，未来的自己会根据真实经历写信。' : '写下一个愿望、一点困惑，或一件想记住的小事。'}</p></div>`;
    for (const direction of ['received','sent']) {
      const letters = state.letters.filter(l => l.direction === direction);
      $(direction === 'received' ? 'letter-grid-received' : 'letter-grid-sent').innerHTML = (direction === 'received' && pending.length ? `<div class="letter-job-note">${FS.icon('clock')} ${pending.length} 封回响正在准备。</div>` : '') + (letters.length ? letters.map(card).join('') : empty(direction));
    }
  }
  function renderGoals() {
    const list=$('goals-list');if(list)list.innerHTML = goals.length ? goals.map(g => { const milestones = state.milestones.filter(m => String(m.goal_id) === String(g.id)); const total = g.milestone_count ?? milestones.length, complete = g.completed_count ?? milestones.filter(m => m.completed).length; return `<article class="goal-card"><div><span class="goal-date">${g.target_date ? '期待 ' + escape(shortDate(g.target_date)) : '按自己的节奏'}${g.updated_at!==g.created_at?' · 计划已调整':''}</span><h3>${escape(g.title)}</h3><p>${escape(g.description || '一个由你亲自选择的方向。')}</p></div><div class="goal-progress">${total ? `<span>已确认 ${complete} / ${total} 个里程碑</span><progress value="${complete}" max="${total}"></progress>` : '<span>还没有里程碑，不预设完成度。</span>'}</div><div class="goal-actions"><button class="button button-secondary" type="button" data-decompose="${g.id}">拆成小行动${FS.icon('arrow-right')}</button><button class="icon-button" type="button" data-edit-goal="${g.id}" aria-label="编辑目标">${FS.icon('edit')}</button><button class="icon-button" type="button" data-delete-goal="${g.id}" aria-label="删除目标">${FS.icon('trash')}</button></div></article>`; }).join('') : '<div class="goals-empty">先确定一个你在意的方向，再慢慢找到下一小步。</div>';
    $('milestone-goal').innerHTML = '<option value="">独立的小计划</option>' + goals.map(g => `<option value="${g.id}">${escape(g.title)}</option>`).join('');
  }
  function showEvent(id) {
    selectedEvent = history.get(String(id)) || state.events.find(e => String(e.id) === String(id));
    if (!selectedEvent) { FS.toast('这条记录尚未载入，可展开更早的行动。'); return; }
    const e = selectedEvent;
    if(!viewedEvents.has(String(e.id))){viewedEvents.add(String(e.id));FS.track?.('echo_viewed',e.id);}
    e.timing_review_required ||= state.sessions.find(s => String(s.id) === String(e.session_id))?.timing_review_required;
    $('event-label').textContent = 'A REAL MOMENT'; $('event-title').textContent = e.title; $('complete-milestone').hidden = true;
    const letterStatus = ({ready:'这次行动的回响信已放入信箱。',pending:'行动已保存，来信正在准备。',queued:'行动已保存，来信等待生成。',running:'正在生成回响，完成后会更新信箱。',failed:'行动已保存，来信生成尚未完成。',disabled:'自动来信已关闭。',deleted:'这次行动的来信已由你删除。'})[e.letter_status] || '';
    $('event-details').innerHTML = `${e.timing_review_required ? '<p class="source-adjusted-note">离线或时间变化导致部分区间待核对，请按真实情况校正。</p>' : ''}<div class="event-facts"><div><small>你确认的结果</small><strong>${results[e.result] || '真实记录'}</strong></div><div><small>记录时长 · 非注意力测量</small><strong>${Math.floor(e.elapsed_seconds/60)} 分 ${Math.floor(e.elapsed_seconds%60)} 秒</strong></div></div><p class="event-reflection">${e.reflection ? '“'+escape(e.reflection)+'”' : '这次没有留下反思。真实的行动，已经在这里。'}</p><p class="event-source">${escape(fullDate(e.created_at))} · 来源：沉浸 #${e.session_id}<br>${letterStatus}</p><div class="event-edit-actions"><button class="text-link" type="button" data-edit-event="${e.id}">${FS.icon('edit')}校正记录</button><button class="text-link" type="button" data-retry-event="${e.id}" data-rewrite="${e.letter_status === 'ready'}">${e.letter_status === 'ready' ? '确认重写回响信' : '重试 / 生成来信'}</button><button class="icon-button" type="button" data-delete-event="${e.id}" aria-label="删除行动及关联内容">${FS.icon('trash')}</button></div><form id="event-feedback-form" class="feedback-form"><p>这份回响，对你有帮助吗？<span> 可跳过</span></p><div class="feedback-options"><label><input type="radio" name="helpful" value="yes">有帮助</label><label><input type="radio" name="helpful" value="no">没太帮到</label><label><input type="radio" name="helpful" value="skip" checked>暂不评价</label></div><p>这次体验让你感觉…</p><div class="feedback-options"><label><input type="radio" name="autonomy" value="understood">被理解</label><label><input type="radio" name="autonomy" value="pressured">有压力</label><label><input type="radio" name="autonomy" value="neutral" checked>中性 / 跳过</label></div><button class="button button-secondary" type="submit">保存我的感受</button></form>`;
    $('event-feedback-form').onsubmit = ev => { ev.preventDefault(); action(async () => { const data = Object.fromEntries(new FormData(ev.target)); await FS.api('/api/feedback',{method:'POST',body:{event_id:e.id,helpful:data.helpful === 'skip' ? null:data.helpful === 'yes',autonomy:data.autonomy}}); $('event-dialog').close();await refresh();const node=document.querySelector(`[data-event="${e.id}"]`);if(node){node.classList.add('just-synced');$('timeline-scroll').scrollLeft=Math.max(0,node.offsetLeft-$('timeline-scroll').clientWidth/2+node.offsetWidth/2);node.scrollIntoView({behavior:'smooth',block:'center'});}FS.toast('感受已保存，任务进度节点已同步。'); },ev.submitter); };
    open('event-dialog');
  }
  function editEvent(id) { selectedEvent = history.get(String(id)) || state.events.find(e => String(e.id) === String(id)); const e = selectedEvent; $('edit-event-result').value = e.result; $('edit-event-minutes').value = Math.floor(e.elapsed_seconds/60); $('edit-event-seconds').value = Math.floor(e.elapsed_seconds%60); $('edit-event-reflection').value = e.reflection || ''; $('event-dialog').close(); open('event-edit-dialog'); }
  function showMilestone(id) {
    selectedMilestone = state.milestones.find(m => String(m.id) === String(id)); if (!selectedMilestone) return;
    const m = selectedMilestone, goal = goals.find(g => String(g.id) === String(m.goal_id)); $('event-label').textContent = 'A POSSIBILITY, NOT A PROMISE'; $('event-title').textContent = m.title;
    $('event-details').innerHTML = `<div class="event-facts"><div><small>你期待的日期</small><strong>${escape(m.date)}</strong></div><div><small>计划状态</small><strong>${m.completed ? '你已确认完成' : '计划 · 尚未完成'}</strong></div></div><p class="event-source">${goal ? '关联目标：' + escape(goal.title) : '独立的小计划'}<br>计划的完成，只来自你的亲自确认。</p><div class="event-edit-actions"><button type="button" class="text-link" data-edit-milestone="${m.id}">${FS.icon('edit')}调整计划</button><button type="button" class="text-link" data-delete-milestone="${m.id}">${FS.icon('trash')}取消计划</button></div>`;
    $('complete-milestone').hidden = false; $('complete-milestone').innerHTML = `${m.completed ? '改回待完成' : '确认我已完成'}${FS.icon('check')}`; open('event-dialog');
  }
  function editMilestone(id = null) { editingMilestone = id; const m = state.milestones.find(x => String(x.id) === String(id)); $('milestone-form').reset(); if (m) { $('milestone-title').value = m.title; $('milestone-date').value = m.date; $('milestone-goal').value = m.goal_id || ''; } $('event-dialog').close(); open('milestone-dialog'); }
  async function showLetter(id) {
    selectedLetter = state.letters.find(l => String(l.id) === String(id)); if (!selectedLetter) { const data=await FS.api('/api/letters/'+encodeURIComponent(id)); selectedLetter=data.letter; state.letters.push(selectedLetter); } const l = selectedLetter;
    $('letter-direction').textContent = l.locked ? 'SEALED UNTIL YOUR CHOSEN MOMENT' : l.direction === 'received' ? 'A LETTER FROM YOUR IDEAL SELF' : 'A LETTER TO THE YOU AHEAD';
    $('letter-date').textContent = l.locked ? `约定 ${fullDate(l.open_at)} 开启` : fullDate(l.created_at); $('letter-read-title').textContent = l.title;
    $('letter-read-body').textContent = l.locked ? '这封信已被好好封存。约定的时间到来后，正文才会向你展开。' : l.body;
    $('letter-signature').textContent = l.locked ? '—— 留给那个时刻的你' : l.direction === 'received' ? '—— 你想成为的那个自己' : '—— 此刻的我';
    $('letter-provenance').textContent = l.locked ? '当前未读取封存正文；开启时间以服务器为准。' : l.direction === 'received' ? `理想自我视角 · 基于${l.source_id ? '本次行动':'首次建档'}生成 · 画像版本 ${l.persona_version || 1}${l.source_id ? ' · 来源行动 #' + l.source_id : ''}。${l.source_adjusted ? '依据已调整：这封旧信保留原文，重写须由你确认。' : '这不是对真实未来的预言。'}` : `已保存在应用内信箱 · ${l.allow_memory ? '你允许这封信用于长期理解' : '未授权用于长期记忆'}。`;
    $('reading-memory-row').hidden = l.direction !== 'sent' || !!l.locked; $('reading-memory').checked = !!l.allow_memory;
    const old = $('letter-rewrite-button'); if (old) old.remove();
    if (l.source_id && !l.locked) { const b = document.createElement('button'); b.id = 'letter-rewrite-button'; b.type = 'button'; b.className = 'text-link'; b.textContent = l.source_adjusted ? '依据已调整 · 确认重写这封信' : '确认重写这封信'; b.dataset.retryEvent = l.source_id; b.dataset.rewrite = 'true'; $('letter-provenance').after(b); }
    open('letter-dialog');
    if(!l.locked&&!viewedLetters.has(String(l.id))){viewedLetters.add(String(l.id));FS.track?.('letter_opened',l.id);}
    if (!l.locked && !l.is_read) { await FS.api(`/api/letters/${l.id}`,{method:'PATCH',body:{is_read:true}}); l.is_read = true; renderMail(); }
  }
  function editGoal(id = null) { editingGoal = id; const g = goals.find(x => String(x.id) === String(id)); $('goal-form').reset(); if (g) ['title','description','target_date'].forEach(key => $('goal-form').elements[key].value = g[key] || ''); open('goal-dialog'); }
  async function decompose(id) {
    decomposingGoal = goals.find(g => String(g.id) === String(id));
    open('decompose-dialog'); $('decompose-steps').innerHTML = '<p class="loading-inline">正在根据你的目标拟定小步草稿…</p>';
    const saved = FS.load(`goal-steps-${id}`,null);
    const data = saved || await FS.api(`/api/goals/${id}/decompose`,{method:'POST',body:{}});
    steps = data.steps || []; $('decompose-provider').textContent = `${data.model?.label || '目标行动草稿'} · 以下只是提议，请按自己的情况修改。`;
    FS.store(`goal-steps-${id}`,data); renderSteps();
  }
  function renderSteps() {
    const available = state.milestones.filter(m => String(m.goal_id) === String(decomposingGoal.id));
    $('decompose-steps').innerHTML = steps.map((s,i) => `<form class="decomposition-step" data-step="${i}"><span class="eyebrow">SMALL STEP ${String(i+1).padStart(2,'0')}</span><div class="field"><label>行动名称<input name="title" value="${escape(s.title)}" maxlength="300" required></label></div><div class="field"><label>第一步<input name="first_step" value="${escape(s.first_step)}" maxlength="300" required></label></div><div class="field"><label>完成标准<input name="done_criteria" value="${escape(s.done_criteria)}" maxlength="300" required></label></div><div class="decomposition-row"><div class="field"><label>计划分钟<input name="planned_minutes" type="number" min="1" max="180" value="${Number(s.planned_minutes) || 15}" required></label></div><div class="field"><label>关联里程碑<select name="milestone_id"><option value="">暂不关联</option>${available.map(m => `<option value="${m.id}" ${String(s.milestone_id) === String(m.id) ? 'selected':''}>${escape(m.title)}</option>`).join('')}</select></label></div></div><div class="step-save-row">${s.task_id ? `<a class="button button-secondary" href="/focus?task=${s.task_id}">去准备这一步${FS.icon('arrow-right')}</a><span>已由你确认保存</span>` : '<button class="button button-primary" type="submit">确认保存这个行动</button>'}</div></form>`).join('') || '<p class="milestone-note">这次没有生成有效草稿。你仍然可以直接在沉浸页手动设定行动。</p>';
    $('decompose-steps').querySelectorAll('form').forEach(form => {
      const i = Number(form.dataset.step);
      if (steps[i].task_id) form.querySelectorAll('input,select').forEach(el => el.disabled = true);
      form.oninput = () => { Object.assign(steps[i],Object.fromEntries(new FormData(form))); FS.store(`goal-steps-${decomposingGoal.id}`,{steps,model:{label:$('decompose-provider').textContent.split(' · ')[0]}}); };
      form.onsubmit = e => { e.preventDefault(); action(async () => { const body = Object.fromEntries(new FormData(form)); body.planned_minutes = Number(body.planned_minutes); body.goal_id = decomposingGoal.id; body.milestone_id = body.milestone_id ? Number(body.milestone_id):null; const data = await FS.api('/api/tasks',{method:'POST',body}); Object.assign(steps[i],body,{task_id:data.task.id}); FS.store(`goal-steps-${decomposingGoal.id}`,{steps,model:{label:$('decompose-provider').textContent.split(' · ')[0]}}); renderSteps(); FS.toast('行动已保存，尚未开始计时。'); },e.submitter); };
    });
  }
  document.addEventListener('click', e => {
    const node = e.target.closest('[data-event],[data-letter],[data-milestone],[data-close],[data-retry-event],[data-delete-event],[data-edit-event],[data-delete-milestone],[data-edit-milestone],[data-edit-goal],[data-delete-goal],[data-decompose]'); if (!node) return;
    if (node.dataset.close) $(node.dataset.close).close();
    if (node.dataset.event) showEvent(node.dataset.event);
    if (node.dataset.milestone) showMilestone(node.dataset.milestone);
    if (node.dataset.editEvent) editEvent(node.dataset.editEvent);
    if (node.dataset.editMilestone) editMilestone(node.dataset.editMilestone);
    if (node.dataset.editGoal) editGoal(node.dataset.editGoal);
    if (node.dataset.letter) action(() => showLetter(node.dataset.letter),node);
    if (node.dataset.decompose) action(() => decompose(node.dataset.decompose),node);
    if (node.dataset.retryEvent && (node.dataset.rewrite !== 'true' || confirm('按当前已更正的事实重新生成，并替换这条行动原有的回响信？'))) action(async () => { const data = await FS.api(`/api/events/${node.dataset.retryEvent}/letter`,{method:'POST',body:{rewrite:node.dataset.rewrite === 'true'}}); await refresh(); FS.toast(data.event?.letter_status === 'disabled' ? '自动来信已关闭，请先在画像中开启。' : data.event?.letter_status === 'ready' && data.letter ? '回响信已完成更新。' : '生成请求已保存，完成后信箱会更新。'); },node);
    if (node.dataset.deleteEvent && confirm('删除这条行动记录？关联的来信、计时和反思记忆也会删除。')) action(async () => { await FS.api(`/api/events/${node.dataset.deleteEvent}`,{method:'DELETE',body:{}}); history.delete(node.dataset.deleteEvent); $('event-dialog').close(); await refresh(); FS.toast('记录及关联内容已删除。'); },node);
    if (node.dataset.deleteMilestone && confirm('取消这个未来计划？过去的行动不会改变。')) action(async () => { await FS.api(`/api/milestones/${node.dataset.deleteMilestone}`,{method:'DELETE',body:{}}); $('event-dialog').close(); await refresh(); },node);
    if (node.dataset.deleteGoal && confirm('删除这个目标？已发生的行动不会改写，关联关系会按服务端规则解除。')) action(async () => { await FS.api(`/api/goals/${node.dataset.deleteGoal}`,{method:'DELETE',body:{}}); FS.store(`goal-steps-${node.dataset.deleteGoal}`,null); await refresh(); },node);
  });
  $('load-more-events').onclick = e => action(loadMore,e.currentTarget);
  $('complete-milestone').onclick = e => action(async () => { await FS.api(`/api/milestones/${selectedMilestone.id}`,{method:'PATCH',body:{completed:!selectedMilestone.completed}}); $('event-dialog').close(); await refresh(); FS.toast('计划状态已由你更新。'); },e.currentTarget);
  $('event-edit-form').onsubmit = e => { e.preventDefault(); action(async () => { const body = {result:$('edit-event-result').value,elapsed_seconds:Number($('edit-event-minutes').value)*60+Number($('edit-event-seconds').value),reflection:$('edit-event-reflection').value}; const data = await FS.api(`/api/events/${selectedEvent.id}`,{method:'PATCH',body}); if (data.event) history.set(String(data.event.id),data.event); $('event-edit-dialog').close(); await refresh(); showEvent(selectedEvent.id); FS.toast('事实已更正，关联旧信会注明依据变化。'); },e.submitter); };
  $('delete-letter').onclick = e => { if (confirm('删除这封信？原有行动记录会保留。')) action(async () => { await FS.api(`/api/letters/${selectedLetter.id}`,{method:'DELETE',body:{}}); $('letter-dialog').close(); await refresh(); FS.toast('这封信已删除。'); },e.currentTarget); };
  $('reading-memory').onchange = e => { const input = e.target, allowed = input.checked; if (busy) { input.checked = !!selectedLetter.allow_memory; return; } action(async () => { try { const data = await FS.api(`/api/letters/${selectedLetter.id}`,{method:'PATCH',body:{allow_memory:allowed}}); selectedLetter.allow_memory = data.letter.allow_memory; $('letter-provenance').textContent = `已保存在应用内信箱 · ${allowed ? '你允许这封信用于长期理解' : '未授权用于长期记忆'}。`; FS.toast(allowed ? '已授权；新增理解仍需你在画像页确认。' : '已撤回授权，关联记忆已移除。'); } catch(err) { input.checked = !allowed; throw err; } },input); };
  $('back-today').onclick = () => { const node = $('today-node'); if (node) $('timeline-scroll').scrollLeft = node.offsetLeft - $('timeline-scroll').clientWidth/2 + node.offsetWidth/2; };
  document.querySelectorAll('[data-mail-tab]').forEach(button => button.onclick = () => { tab = button.dataset.mailTab; document.querySelectorAll('[data-mail-tab]').forEach(b => b.classList.toggle('active',b === button)); const drawer = button.closest('.mail-drawer'); drawer?.classList.add('drawer-awake'); setTimeout(() => drawer?.classList.remove('drawer-awake'),420); });
  $('write-letter').onclick = () => { const draft = FS.load('letter-draft',{}); $('letter-title').value = draft.title || ''; $('letter-body').value = draft.body || ''; $('letter-memory').checked = !!draft.allow_memory; $('letter-open-at').value = draft.open_at || ''; open('compose-dialog'); };
  $('letter-form').oninput = () => { FS.store('letter-draft',{title:$('letter-title').value,body:$('letter-body').value,allow_memory:$('letter-memory').checked,open_at:$('letter-open-at').value}); $('draft-status').textContent = '草稿已保存在当前设备'; };
  $('letter-form').onsubmit = e => { e.preventDefault(); action(async () => { const future = $('letter-open-at').value; if (future && new Date(future).getTime() <= Date.now()) { FS.toast('请选择一个未来的开启时间，或留空即刻存入。'); return; } await FS.api('/api/letters',{method:'POST',body:{title:$('letter-title').value,body:$('letter-body').value,allow_memory:$('letter-memory').checked,open_at:future ? new Date(future).toISOString():null}}); FS.store('letter-draft',{}); $('letter-form').reset(); $('compose-dialog').close(); tab = 'sent'; document.querySelector('[data-mail-tab=sent]').click(); await refresh(); FS.toast(future ? '信已封存，到约定的时刻再见。' : '这封信，已好好收进信箱。'); },e.submitter); };
  $('new-milestone').onclick = () => editMilestone();
  $('milestone-form').onsubmit = e => { e.preventDefault(); action(async () => { const body = Object.fromEntries(new FormData($('milestone-form'))); body.goal_id = body.goal_id ? Number(body.goal_id):null; await FS.api(editingMilestone ? `/api/milestones/${editingMilestone}`:'/api/milestones',{method:editingMilestone?'PATCH':'POST',body}); $('milestone-form').reset(); $('milestone-dialog').close(); await refresh(); FS.toast(editingMilestone ? '计划已调整，过去的行动保持原样。' : '未来的时间轴，多了一点期待。'); },e.submitter); };
  if($('new-goal'))$('new-goal').onclick = () => editGoal();
  $('goal-form').onsubmit = e => { e.preventDefault(); action(async () => { const body = Object.fromEntries(new FormData($('goal-form'))); body.target_date ||= null; await FS.api(editingGoal ? `/api/goals/${editingGoal}`:'/api/goals',{method:editingGoal?'PATCH':'POST',body}); if (editingGoal) FS.store(`goal-steps-${editingGoal}`,null); $('goal-dialog').close(); await refresh(); FS.toast('这个方向已由你保存。'); },e.submitter); };
  function paintReview(r,meta={}) {
    selectedReview=r.id;$('review-title').textContent=r.title;$('review-body').textContent=r.body;$('review-period').textContent=`${r.period_start} — ${r.period_end}`;
    $('review-model').textContent=`${r.model?.label||meta.label||'基于本周实际记录整理'} · ${r.source_adjusted?'依据已调整，这份历史回顾保留原文。可重新生成本周回顾。':'不评价人格，也不比较他人。'}`;
    const labels={session_count:'次沉浸',recorded_minutes:'分钟记录',completed_count:'次完成',partial_count:'次推进',stopped_count:'次主动结束'};
    $('review-stats').innerHTML=Object.entries(r.stats||{}).filter(([k,v])=>k in labels&&typeof v==='number').map(([k,v])=>`<div><strong>${v}</strong><span>${labels[k]}</span></div>`).join('');open('review-dialog');
  }
  if($('weekly-review'))$('weekly-review').onclick=e=>action(async()=>{
    selectedReview=null;$('review-title').textContent='把这一周，轻轻回看。';$('review-body').textContent='正在整理真实记录…';$('review-stats').innerHTML='';$('review-period').textContent='';$('review-model').textContent='';open('review-dialog');
    try{const data=await FS.api('/api/reviews/weekly',{method:'POST',body:{}});paintReview(data.review,data.model);}catch(error){$('review-body').textContent='这次回顾尚未生成。真实记录仍在，可以关闭后重试。';throw error;}
  },e.currentTarget);
  function editing(){return !!document.querySelector('#compose-dialog[open],#milestone-dialog[open],#event-edit-dialog[open],#goal-dialog[open],#decompose-dialog[open]')||!!document.activeElement?.closest('#event-feedback-form');}
  async function syncView(){
    if(busy||document.hidden||editing()){refreshPending=true;return;}refreshPending=false;
    const letter=$('letter-dialog').open?selectedLetter?.id:null,event=$('event-dialog').open&&$('event-feedback-form')?selectedEvent?.id:null,review=$('review-dialog').open?selectedReview:null;
    await refresh();
    if(letter)await showLetter(letter);
    if(event){try{const data=await FS.api('/api/events/'+event);history.set(String(event),data.event);showEvent(event);}catch(error){if(error.status===404){history.delete(String(event));$('event-dialog').close();render();}else throw error;}}
    if(review){const data=await FS.api('/api/reviews/'+review);paintReview(data.review);}
  }
  window.addEventListener('fs:sync',()=>syncView().catch(()=>{}));
  window.addEventListener('online',()=>syncView().catch(()=>{}));
  document.querySelectorAll('.echo-dialog').forEach(dialog=>dialog.addEventListener('close',()=>{if(refreshPending)syncView().catch(()=>{});}));
  window.addEventListener('fs:draft',event=>{if(event.detail?.key!=='letter-draft'||busy||!$('compose-dialog').open||$('letter-form').contains(document.activeElement))return;const draft=event.detail.value||{};$('letter-title').value=draft.title||'';$('letter-body').value=draft.body||'';$('letter-memory').checked=!!draft.allow_memory;$('letter-open-at').value=draft.open_at||'';$('draft-status').textContent='已同步另一设备的草稿。';});
  refresh().then(async () => { $('back-today').click(); const p = new URLSearchParams(location.search); if (p.get('event')) { if (!history.has(p.get('event'))) { const data = await FS.api('/api/events/' + encodeURIComponent(p.get('event'))); history.set(String(data.event.id),data.event); } showEvent(p.get('event')); } if (p.get('session')) { const found = state.events.find(e => String(e.session_id) === p.get('session')); if (found) { history.set(String(found.id),found); showEvent(found.id); } } if (p.get('letter')) await showLetter(p.get('letter')); if(p.get('review')){const data=await FS.api('/api/reviews/'+encodeURIComponent(p.get('review')));paintReview(data.review);} }).catch(err => FS.toast(err.message,'error'));
})();
