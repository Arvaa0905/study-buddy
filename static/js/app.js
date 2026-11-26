document.addEventListener('DOMContentLoaded', () => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
  document.querySelectorAll('[data-pw-toggle]').forEach(btn => btn.addEventListener('click', () => {
    const input = btn.previousElementSibling;
    if (!input) return;
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    btn.textContent = show ? 'Hide' : 'Show';
    btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  }));
  const authForm = document.getElementById('auth-form');
  if (authForm) {
    const pwInput = document.getElementById('auth-password');
    const meter = document.getElementById('pw-strength');
    const meterLabel = document.getElementById('pw-strength-label');
    if (pwInput && meter && meterLabel) {
      pwInput.addEventListener('input', () => {
        const val = pwInput.value;
        meter.hidden = val.length === 0;
        let score = 0;
        if (val.length >= 8) score++;
        if (/[A-Z]/.test(val) && /[a-z]/.test(val)) score++;
        if (/\d/.test(val)) score++;
        if (/[^A-Za-z0-9]/.test(val)) score++;
        meter.dataset.score = String(score);
        const labels = ['Too short (min 8 chars)', 'Fair password', 'Good password', 'Strong password', 'Very strong password'];
        meterLabel.textContent = val.length < 8 ? labels[0] : labels[Math.max(1, score)];
      });
    }
    authForm.addEventListener('submit', () => {
      const btn = authForm.querySelector('.auth-submit');
      if (btn && !btn.disabled) {
        btn.disabled = true;
        const label = btn.querySelector('span');
        if (label && btn.dataset.loadingText) label.textContent = btn.dataset.loadingText;
      }
    });
  }
  document.querySelectorAll('[data-confirm]').forEach(b => b.addEventListener('click', e => {
    if (!confirm(b.dataset.confirm)) e.preventDefault();
  }));
  const animatedLists = document.querySelectorAll('[data-animated-list]');
  if (animatedLists.length) {
    import('/static/js/animated-list.js')
      .then(mod => animatedLists.forEach(el => mod.enhanceAnimatedList(el)))
      .catch(() => {});
  }
  // Notes editor
  const noteForm = document.getElementById('note-form');
  if (noteForm) {
    const id = document.getElementById('note-id'), title = document.getElementById('note-title'),
      subject = document.getElementById('note-subject'), content = document.getElementById('note-content'),
      label = document.getElementById('editor-label'), count = document.getElementById('char-count'),
      deleteWrap = document.getElementById('delete-wrap'), deleteForm = document.getElementById('delete-form');
    function clearNote() { id.value=''; title.value=''; subject.value=''; content.value=''; label.textContent='NEW NOTE'; deleteWrap.hidden=true; count.textContent='0 characters'; }
    function updateCount(){ count.textContent = `${content.value.length.toLocaleString()} characters`; }
    document.getElementById('new-note').addEventListener('click', () => { clearNote(); title.focus(); });
    document.getElementById('clear-note').addEventListener('click', clearNote);
    content.addEventListener('input', updateCount);
    document.querySelectorAll('.note-list-item').forEach(item => item.addEventListener('click', () => {
      id.value=item.dataset.noteId; title.value=item.dataset.title; subject.value=item.dataset.subject;
      content.value=item.dataset.content; label.textContent='EDITING NOTE'; deleteWrap.hidden=false;
      deleteForm.action=`/notes/${id.value}/delete`; updateCount();
    }));
  }
  // Chat interface
  const chatForm = document.getElementById('chat-form');
  if (chatForm) {
    const input=document.getElementById('chat-input'), messages=document.getElementById('chat-messages');
    function scrollBottom(){messages.scrollTop=messages.scrollHeight;}
    function renderMarkdown(target, source) {
      if (window.marked && window.DOMPurify) {
        const mathBlocks = [];
        const escHtml = s => s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
        // Protect code blocks first so $ inside code isn't treated as math, then protect LaTeX from marked
        const codeBlocks = [];
        let prepared = String(source).replace(/(```[\s\S]*?```|`[^`\n]+`)/g, m => {
          codeBlocks.push(m);
          return `@@CODE_${codeBlocks.length - 1}@@`;
        });
        prepared = prepared.replace(/(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|(?<!\\)\$(?!\s)([^\n$]+?)(?<!\s)\$)/g, m => {
          mathBlocks.push(m);
          return `@@MATH_${mathBlocks.length - 1}@@`;
        });
        prepared = prepared.replace(/@@CODE_(\d+)@@/g, (_, i) => codeBlocks[Number(i)]);
        let html = window.DOMPurify.sanitize(window.marked.parse(prepared, { breaks: true, gfm: true }));
        html = html.replace(/@@MATH_(\d+)@@/g, (_, i) => `<span class="math-tex">${escHtml(mathBlocks[Number(i)])}</span>`);
        target.innerHTML = html;
        if (window.renderMathInElement) {
          window.renderMathInElement(target, {
            delimiters: [
              { left: '$$', right: '$$', display: true },
              { left: '\\[', right: '\\]', display: true },
              { left: '$', right: '$', display: false },
              { left: '\\(', right: '\\)', display: false }
            ],
            throwOnError: false
          });
        }
        target.querySelectorAll('pre code').forEach(block => { if (window.hljs) window.hljs.highlightElement(block); });
        target.querySelectorAll('pre').forEach(pre => {
          const copy=document.createElement('button'); copy.className='code-copy'; copy.type='button'; copy.textContent='Copy';
          copy.addEventListener('click', async () => { try { await navigator.clipboard.writeText(pre.querySelector('code')?.innerText || pre.innerText); copy.textContent='Copied'; setTimeout(()=>copy.textContent='Copy',1400); } catch (_) { copy.textContent='Select code to copy'; } });
          pre.append(copy);
        });
      } else { target.textContent=source; }
    }
    let strandsModulePromise = null;
    function loadStrands() {
      if (!strandsModulePromise) {
        strandsModulePromise = import('/static/js/strands.js').catch(() => null);
      }
      return strandsModulePromise;
    }
    function addMessage(role, text, pending=false) {
      const welcome=messages.querySelector('.welcome-message'); if(welcome) welcome.remove();
      const row=document.createElement('div'); row.className=`message ${role==='user'?'user-message':'assistant-message'} message-enter`;
      const avatar=document.createElement('div'); avatar.className='message-avatar'; avatar.textContent=role==='user'?'Y':'✧';
      const body=document.createElement('div'); body.className='message-body';
      const who=document.createElement('small'); who.textContent=role==='user'?'You':'Study Buddy';
      const txt=document.createElement('div'); txt.className='message-text';
      if (pending) {
        txt.classList.add('thinking-state');
        txt.innerHTML='<div class="thinking-orb-wrap"><div class="thinking-orb"><span></span><span></span><span></span></div><em>Thinking…</em></div>';
        const orbEl = txt.querySelector('.thinking-orb');
        loadStrands().then(mod => {
          if (mod && txt.classList.contains('thinking-state') && orbEl) {
            const orb = mod.mountStrands(orbEl, { lightMode: true, listening: true, energy: 0.78 });
            if (orb) txt._strandsInstance = orb;
          }
        });
      }
      else if (role==='assistant') { txt.classList.add('markdown-body'); renderMarkdown(txt,text); }
      else { txt.textContent=text; }
      body.append(who,txt); row.append(avatar,body); messages.append(row); scrollBottom(); return txt;
    }
    async function send(text) {
      text=text.trim(); if(!text) return;
      addMessage('user',text); input.value=''; input.style.height='auto';
      const pending=addMessage('assistant','',true);
      const button=chatForm.querySelector('button'); button.disabled=true;
      try {
        const response=await fetch('/api/chat/stream',{
          method:'POST',
          headers:{'Content-Type':'application/json','X-CSRFToken':csrfToken},
          body:JSON.stringify({message:text})
        });
        const contentType=response.headers.get('content-type')||'';
        if(!response.ok || contentType.includes('application/json') || !response.body){
          const data=await response.json().catch(()=>({}));
          pending._strandsInstance?.destroy();
          pending.classList.remove('thinking-state'); pending.innerHTML='';
          renderMarkdown(pending,data.answer||data.error||'Something went wrong.');
          return;
        }
        const reader=response.body.getReader();
        const decoder=new TextDecoder();
        let buffer='', accumulated='', started=false;
        while(true){
          const {value, done}=await reader.read();
          if(done) break;
          buffer+=decoder.decode(value,{stream:true});
          const lines=buffer.split('\n\n');
          buffer=lines.pop()||'';
          for(const block of lines){
            const dataLine=block.split('\n').find(l=>l.startsWith('data: '));
            if(!dataLine) continue;
            const evt=JSON.parse(dataLine.slice(6));
            if(evt.type==='chunk' && evt.text){
              if(!started){
                started=true;
                pending._strandsInstance?.destroy();
                pending.classList.remove('thinking-state');
                pending.classList.add('markdown-body');
                pending.innerHTML='';
              }
              accumulated+=evt.text;
              renderMarkdown(pending,accumulated);
              scrollBottom();
            } else if(evt.type==='done' && evt.quiz_topic){
              const launch=document.createElement('a');
              launch.className='btn btn-primary quiz-launch-btn';
              launch.href=evt.saved_quiz_id ? `/quiz?saved_id=${encodeURIComponent(evt.saved_quiz_id)}` : `/quiz?topic=${encodeURIComponent(evt.quiz_topic)}`;
              launch.textContent=`Start custom quiz on ${evt.quiz_topic} →`;
              pending.parentElement.append(launch);
            }
          }
        }
        if(!started){
          pending._strandsInstance?.destroy();
          pending.classList.remove('thinking-state');
          pending.textContent='No response received.';
        }
      } catch(e){
        pending._strandsInstance?.destroy();
        pending.classList.remove('thinking-state'); pending.textContent='Could not connect. Please check your connection and try again.';
      }
      finally {button.disabled=false; scrollBottom(); input.focus();}
    }
    chatForm.addEventListener('submit',e=>{e.preventDefault();send(input.value);});
    input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();chatForm.requestSubmit();}});
    input.addEventListener('input',()=>{input.style.height='auto';input.style.height=Math.min(input.scrollHeight,140)+'px';});
    document.querySelectorAll('[data-prompt]').forEach(b=>b.addEventListener('click',()=>{input.value=b.dataset.prompt;send(input.value);}));
    document.getElementById('clear-chat').addEventListener('click',()=>{messages.innerHTML='<div class="welcome-message"><div class="welcome-art">✦</div><h2>What are we learning today?</h2><p>This only clears the current view; saved chat history stays in your account.</p></div>';});
    messages.querySelectorAll('.message-text[data-markdown]').forEach(el => {
      renderMarkdown(el, el.getAttribute('data-markdown') || '');
    });
    scrollBottom();
  }
  // Quiz
  const picker=document.getElementById('topic-picker');
  if(picker){
    const stage=document.getElementById('quiz-stage'), result=document.getElementById('quiz-result');
    let topic='', questions=[], answers=[], index=0, savedQuizId=null;
    const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    async function start(t){
      const r=await fetch('/api/quiz/'+encodeURIComponent(t)); const data=await r.json();
      if(!r.ok){alert(data.error||'Could not load quiz');return;}
      beginQuiz(data.topic||t, data.questions, null);
    }
    async function startSaved(id){
      const r=await fetch('/api/quiz/saved/'+encodeURIComponent(id)); const data=await r.json();
      if(!r.ok){alert(data.error||'Could not load saved quiz');return;}
      beginQuiz(data.topic, data.questions, data.id);
    }
    function beginQuiz(t, qs, sId=null){
      topic=t;questions=qs;answers=Array(questions.length).fill(null);index=0;savedQuizId=sId;
      picker.hidden=true;result.hidden=true;stage.hidden=false;
      document.getElementById('quiz-topic').textContent=topic;renderQuestion();
    }
    document.querySelectorAll('[data-saved-quiz]').forEach(b=>b.addEventListener('click',()=>startSaved(b.dataset.savedQuiz)));
    document.querySelectorAll('[data-delete-quiz]').forEach(b=>b.addEventListener('click',async(e)=>{
      e.stopPropagation();
      if(!confirm('Delete this saved quiz?')) return;
      const id=b.dataset.deleteQuiz;
      const r=await fetch(`/api/quiz/saved/${encodeURIComponent(id)}/delete`,{method:'POST',headers:{'X-CSRFToken':csrfToken}});
      if(r.ok){ document.querySelector(`[data-saved-card="${id}"]`)?.remove(); }
    }));
    const customForm=document.getElementById('custom-quiz-form');
    if(customForm){
      const topicInput=document.getElementById('custom-topic'),
        diffInput=document.getElementById('custom-difficulty'),
        countInput=document.getElementById('custom-count'),
        genBtn=document.getElementById('generate-quiz-btn'),
        statusEl=document.getElementById('quiz-gen-status');
      async function generateCustomQuiz(reqTopic){
        const cleanTopic=(reqTopic||'').trim();
        if(!cleanTopic){topicInput.focus();return;}
        genBtn.disabled=true; genBtn.textContent='Generating quiz…';
        statusEl.hidden=false; statusEl.textContent=`Creating and saving a ${countInput.value}-question ${diffInput.value} quiz on "${cleanTopic}"…`;
        try{
          const r=await fetch('/api/quiz/generate',{
            method:'POST',
            headers:{'Content-Type':'application/json','X-CSRFToken':csrfToken},
            body:JSON.stringify({topic:cleanTopic,difficulty:diffInput.value,num_questions:Number(countInput.value)})
          });
          const data=await r.json();
          if(!r.ok){statusEl.textContent=data.error||'Could not generate quiz.';return;}
          statusEl.hidden=true;
          beginQuiz(data.topic, data.questions, data.id || null);
        }catch(_){
          statusEl.textContent='Could not connect to generate quiz. Please try again.';
        }finally{
          genBtn.disabled=false; genBtn.textContent='Generate quiz ✦';
        }
      }
      customForm.addEventListener('submit',e=>{e.preventDefault();generateCustomQuiz(topicInput.value);});
      const params=new URLSearchParams(window.location.search);
      const requestedSavedId=params.get('saved_id');
      const requestedTopic=params.get('topic');
      if(requestedSavedId && /^\d+$/.test(requestedSavedId)){
        startSaved(requestedSavedId);
      } else if(requestedTopic && requestedTopic.trim()){
        topicInput.value=requestedTopic.trim();
        generateCustomQuiz(requestedTopic.trim());
      }
    }
    function renderQuestion(){
      const q=questions[index];document.getElementById('question-count').textContent=`QUESTION ${index+1} OF ${questions.length}`;
      document.getElementById('progress-fill').style.width=((index+1)/questions.length*100)+'%';
      document.getElementById('question-area').innerHTML=`<h2 class="question-title">${esc(q.q)}</h2><div class="answer-options">${q.options.map((o,i)=>`<button class="answer-option ${answers[index]===i?'selected':''}" data-answer="${i}"><span class="option-letter">${String.fromCharCode(65+i)}</span><span>${esc(o)}</span><span class="option-check">✓</span></button>`).join('')}</div>`;
      document.querySelectorAll('[data-answer]').forEach(b=>b.addEventListener('click',()=>{answers[index]=Number(b.dataset.answer);renderQuestion();}));
      document.getElementById('prev-question').disabled=index===0;
      document.getElementById('next-question').hidden=index===questions.length-1;
      document.getElementById('submit-quiz').hidden=index!==questions.length-1;
    }
    document.querySelectorAll('[data-topic]').forEach(b=>b.addEventListener('click',()=>start(b.dataset.topic)));
    document.getElementById('prev-question').addEventListener('click',()=>{if(index>0){index--;renderQuestion();}});
    document.getElementById('next-question').addEventListener('click',()=>{if(answers[index]===null){alert('Choose an answer before continuing.');return;}index++;renderQuestion();});
    document.getElementById('submit-quiz').addEventListener('click',async()=>{
      if(answers[index]===null){alert('Choose an answer before finishing.');return;}
      const btn=document.getElementById('submit-quiz');btn.disabled=true;
      try{
        const r=await fetch('/api/quiz/submit',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrfToken},body:JSON.stringify({topic,answers,saved_quiz_id:savedQuizId})});
        const d=await r.json();if(!r.ok)throw new Error(d.error||'Could not save result');
        stage.hidden=true;result.hidden=false;document.getElementById('result-title').textContent=d.percent>=80?'Excellent work!':d.percent>=60?'Good progress!':'Keep going — you’ve got this!';
        document.getElementById('result-score').textContent=`${d.score}/${d.total}`;
        document.getElementById('result-copy').textContent=`You answered ${d.score} of ${d.total} correctly (${d.percent}%). Review the explanations below to reinforce your learning.`;
        document.getElementById('review-list').innerHTML=d.review.map((x,i)=>`<div class="review-item ${x.is_correct?'correct':'incorrect'}"><div class="review-head"><b>${i+1}. ${esc(x.q)}</b><span>${x.is_correct?'✓ Correct':'↻ Review'}</span></div><p>Your answer: ${esc(x.chosen)}</p><p>Correct answer: <b>${esc(x.correct)}</b></p><small>${esc(x.why)}</small></div>`).join('');
      }catch(e){alert(e.message);}finally{btn.disabled=false;}
    });
    document.getElementById('retry-quiz').addEventListener('click',()=>{window.location.href='/quiz';});
  }
});
