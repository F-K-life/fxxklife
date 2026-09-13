(() => {
  const questions=[
    {category:'YOUR IDEAL SELF',title:'一年后的你，最希望哪里不一样？',hint:'可以是一件想做到的事，也可以是一种想拥有的状态。',examples:['做事更从容一些','能自信地用英语交流','找到真正想做的事']},
    {category:'WHAT MATTERS TO YOU',title:'为什么，这件事对你很重要？',hint:'也想听听，有什么是你不愿为了进步而牺牲的。',examples:['想拥有更多选择','希望留出陪伴家人的时间','不想以透支自己为代价']},
    {category:'WHERE YOU ARE NOW',title:'最近，你最想推进哪一件事？',hint:'通常卡在哪一步？说说具体的一刻，就够了。',examples:['想学英语，总觉得一小时太长','项目很想做，却不知道从哪下手','总在等待一个完美的开始']},
    {category:'FIND YOUR OWN RHYTHM',title:'什么，曾经帮助过你开始？',hint:'想想一次还不错的经历。现在，你愿意为一件事留出多久？',examples:['目标小一点，先做 10 分钟','安静的环境让我更容易投入','先列出一个具体的第一步']},
    {category:'HOW WE CONNECT',title:'你希望，我怎么和你说话？',hint:'温柔陪伴、清晰直接，还是轻松一点？不想听的话也可以告诉我。',examples:['温柔一点，先听我说','清晰直接，简短一些','轻松一点，像朋友聊天']}
  ];
  const validAnswers=value=>Array.isArray(value)&&value.length===5&&value.every(answer=>typeof answer==='string');
  const storedAnswers=FS.load('onboarding-answers'),existingLocal=validAnswers(storedAnswers)?storedAnswers:null;
  const storedStep=Number(FS.load('onboarding-step',0));
  let answers=existingLocal?.map(answer=>answer.slice(0,2000))||['','','','',''];
  let step=Number.isFinite(storedStep)?Math.min(5,Math.max(0,Math.trunc(storedStep))):0;
  let timer,saveQueue=Promise.resolve(),complete=false,finishing=false,editRevision=0,saveRevision=0;
  let questionRevision=0,questionController,consentEdited=false,answersReady=Boolean(existingLocal);
  const questionCache=new Map(),input=document.querySelector('#onboarding-answer'),status=document.querySelector('#save-status');
  const mode=document.querySelector('#question-mode'),retry=document.querySelector('#retry-question');
  const reuse=document.querySelector('#profile-reuse-consent'),memory=document.querySelector('#memory-consent');
  const localConsents=FS.load('onboarding-consents');
  if(typeof localConsents?.profile_reuse_enabled==='boolean')reuse.checked=localConsents.profile_reuse_enabled;
  if(typeof localConsents?.memory_enabled==='boolean')memory.checked=localConsents.memory_enabled;

  function persist(){if(answersReady)FS.store('onboarding-answers',answers);FS.store('onboarding-step',step);}
  function save(){
    persist();if(finishing||complete||!answersReady)return saveQueue;
    const snapshot=[...answers],version=++saveRevision;status.textContent='正在保存…';
    saveQueue=saveQueue.catch(()=>{}).then(()=>FS.api('/api/onboarding',{method:'POST',body:{answers:snapshot,complete:false}}))
      .then(()=>{if(version===saveRevision)status.textContent='已保存';})
      .catch(()=>{if(version===saveRevision)status.textContent='本机已保留，待连接';});
    return saveQueue;
  }
  function modeText(text,type='static'){mode.textContent=text;mode.dataset.mode=type;}
  function showQuestion(question){
    document.querySelector('#question-title').textContent=question.question||question.title;
    document.querySelector('#question-hint').textContent=question.hint;
    const examples=document.querySelector('#answer-examples');examples.replaceChildren();
    for(const text of question.examples){const button=document.createElement('button');button.type='button';button.textContent=text;examples.append(button);}
  }
  function questionKey(){return JSON.stringify([step,answers.slice(0,step)]);}
  async function personalize(force=false){
    questionController?.abort();const revision=++questionRevision;
    if(step>=5||finishing||complete)return;
    const key=questionKey(),requestedStep=step,typedAtStart=editRevision;
    const cached=questionCache.get(key);
    if(cached&&!force){showQuestion(cached);modeText(cached.model?.mode==='remote'?'AI 个性化提问':'本地引导 · 参考你的回答','ready');return;}
    retry.hidden=true;
    if(!navigator.onLine){modeText('离线题目 · 可以直接作答');retry.hidden=false;return;}
    questionController=new AbortController();const controller=questionController;
    const timeout=setTimeout(()=>controller.abort(),18000);
    modeText('正在调整提问 · 不影响作答','loading');
    try{
      const result=await FS.api('/api/onboarding/question',{method:'POST',signal:controller.signal,body:{answers:[...answers],step:requestedStep}});
      if(typeof result.question!=='string'||!result.question.trim()||typeof result.hint!=='string'||!Array.isArray(result.examples)||!result.examples.length||result.examples.some(value=>typeof value!=='string'))throw new Error('题目格式待调整');
      if(revision!==questionRevision||step!==requestedStep||key!==questionKey()||controller.signal.aborted)return;
      questionCache.set(key,result);
      if(editRevision!==typedAtStart){modeText('保留你正在回答的题目');return;}
      showQuestion(result);
      modeText(result.model?.mode==='remote'?'AI 个性化提问':result.model?.error?'本地引导 · 模型暂未连接':'本地引导 · 参考你的回答','ready');
      mode.title=result.model?.label||'';retry.hidden=!result.model?.error;
    }catch{
      if(revision!==questionRevision||step!==requestedStep)return;
      modeText(navigator.onLine?'固定题目 · 回答不受影响':'离线题目 · 可以直接作答');retry.hidden=false;
    }finally{clearTimeout(timeout);}
  }
  function paint(){
    persist();questionController?.abort();++questionRevision;
    document.querySelector('#question-card').hidden=step===5;
    document.querySelector('#summary-card').hidden=step!==5;
    document.querySelectorAll('.step-dots span').forEach((el,i)=>{el.classList.toggle('active',i===step);el.classList.toggle('done',i<step);});
    document.querySelector('#step-count').textContent=step===5?'最后，确认一下':String(step+1).padStart(2,'0')+' / 05';
    if(step===5){document.querySelectorAll('[data-answer]').forEach(field=>field.value=answers[Number(field.dataset.answer)]||'');return;}
    const question=questions[step];document.querySelector('#question-category').textContent=question.category;
    showQuestion(question);input.value=answers[step]||'';mode.title='';
    document.querySelector('#previous-question').style.visibility=step===0?'hidden':'visible';
    document.querySelector('#next-question').innerHTML=(step===4?'看看我们的理解':'继续')+' '+FS.icon('arrow-right');
    personalize();
  }
  function edited(){++editRevision;answersReady=true;persist();clearTimeout(timer);timer=setTimeout(save,650);status.textContent='正在记录…';}
  input.addEventListener('input',()=>{if(finishing||step>=5)return;answers[step]=input.value;edited();});
  document.querySelector('#answer-examples').onclick=event=>{const button=event.target.closest('button');if(!button||finishing)return;input.value=button.textContent;answers[step]=input.value;edited();input.focus();};
  function advance(){if(finishing||step>=5)return;++editRevision;answersReady=true;answers[step]=input.value;clearTimeout(timer);save();step++;paint();}
  document.querySelector('#next-question').onclick=advance;document.querySelector('#skip-question').onclick=advance;
  document.querySelector('#previous-question').onclick=()=>{if(finishing||step===0)return;++editRevision;answersReady=true;answers[step]=input.value;clearTimeout(timer);save();step--;paint();};
  document.querySelector('#return-questions').onclick=()=>{if(finishing)return;++editRevision;step=4;paint();};
  document.querySelectorAll('[data-answer]').forEach(field=>field.addEventListener('input',()=>{if(finishing)return;answers[Number(field.dataset.answer)]=field.value;edited();}));
  for(const control of [reuse,memory])control.addEventListener('change',()=>{consentEdited=true;FS.store('onboarding-consents',{profile_reuse_enabled:reuse.checked,memory_enabled:memory.checked});});
  retry.onclick=()=>personalize(true);
  document.querySelector('#finish-onboarding').onclick=async()=>{
    if(complete||finishing)return;finishing=true;clearTimeout(timer);questionController?.abort();++questionRevision;
    const controls=[...document.querySelectorAll('#summary-card input,#summary-card textarea,#summary-card button')];
    controls.forEach(control=>control.disabled=true);
    const snapshot=[...answers],consents={profile_reuse_enabled:reuse.checked,memory_enabled:memory.checked};
    try{
      await saveQueue;
      await FS.api('/api/onboarding',{method:'POST',body:{answers:snapshot,complete:true,...consents}});
      complete=true;FS.store('onboarding-answers',null);FS.store('onboarding-consents',null);FS.store('onboarding-step',0);location.href='/chat';
    }catch(error){FS.toast(error.message,'error');finishing=false;controls.forEach(control=>control.disabled=false);}
  };
  window.addEventListener('online',()=>{if(!finishing&&!complete){save();if(step<5)personalize();}});
  window.addEventListener('pagehide',()=>{clearTimeout(timer);questionController?.abort();if(!complete)persist();});
  window.addEventListener('fs:draft',event=>{if(event.detail?.key==='onboarding-answers'&&validAnswers(event.detail.value)&&!finishing&&!complete){answers=[...event.detail.value];answersReady=true;++editRevision;paint();}});
  paint();
  const initialEdit=editRevision;
  FS.state().then(state=>{
    if(finishing||complete)return;
    if(!existingLocal&&editRevision===initialEdit&&validAnswers(state.answers)){answers=state.answers.map(answer=>answer.slice(0,2000));answersReady=true;paint();}
    if(!localConsents&&!consentEdited){reuse.checked=Boolean(state.user?.profile_reuse_enabled);memory.checked=Boolean(state.user?.memory_enabled);}
  }).catch(()=>{});
})();
