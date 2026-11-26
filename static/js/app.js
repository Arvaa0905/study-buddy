document.addEventListener('DOMContentLoaded', () => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
  document.querySelectorAll('[data-confirm]').forEach(b => b.addEventListener('click', e => {
    if (!confirm(b.dataset.confirm)) e.preventDefault();
  }));
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
        target.innerHTML = window.DOMPurify.sanitize(window.marked.parse(source, { breaks: true, gfm: true }));
        target.querySelectorAll('pre code').forEach(block => { if (window.hljs) window.hljs.highlightElement(block); });
        target.querySelectorAll('pre').forEach(pre => {
          const copy=document.createElement('button'); copy.className='code-copy'; copy.type='button'; copy.textContent='Copy';
          copy.addEventListener('click', async () => { try { await navigator.clipboard.writeText(pre.querySelector('code')?.innerText || pre.innerText); copy.textContent='Copied'; setTimeout(()=>copy.textContent='Copy',1400); } catch (_) { copy.textContent='Select code to copy'; } });
          pre.append(copy);
        });
      } else { target.textContent=source; }
    }
    function addMessage(role, text, pending=false) {
      const welcome=messages.querySelector('.welcome-message'); if(welcome) welcome.remove();
      const row=document.createElement('div'); row.className=`message ${role==='user'?'user-message':'assistant-message'} message-enter`;
      const avatar=document.createElement('div'); avatar.className='message-avatar'; avatar.textContent=role==='user'?'Y':'✧';
      const body=document.createElement('div'); body.className='message-body';
      const who=document.createElement('small'); who.textContent=role==='user'?'You':'Study Buddy';
      const txt=document.createElement('div'); txt.className='message-text';
      if (pending) { txt.classList.add('thinking-state'); txt.innerHTML='<span></span><span></span><span></span><em>Putting it together…</em>'; }
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
        const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrfToken},body:JSON.stringify({message:text})});
        const data=await response.json(); pending.classList.remove('thinking-state'); pending.innerHTML=''; renderMarkdown(pending,data.answer||data.error||'Something went wrong.');
      } catch(e){pending.classList.remove('thinking-state'); pending.textContent='Could not connect. Please check your connection and try again.';}
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
    let topic='', questions=[], answers=[], index=0;
    const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    async function start(t){
      const r=await fetch('/api/quiz/'+encodeURIComponent(t)); const data=await r.json();
      if(!r.ok){alert(data.error||'Could not load quiz');return;}
      topic=t;questions=data.questions;answers=Array(questions.length).fill(null);index=0;
      picker.hidden=true;result.hidden=true;stage.hidden=false;
      document.getElementById('quiz-topic').textContent=topic;renderQuestion();
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
        const r=await fetch('/api/quiz/submit',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrfToken},body:JSON.stringify({topic,answers})});
        const d=await r.json();if(!r.ok)throw new Error(d.error||'Could not save result');
        stage.hidden=true;result.hidden=false;document.getElementById('result-title').textContent=d.percent>=80?'Excellent work!':d.percent>=60?'Good progress!':'Keep going — you’ve got this!';
        document.getElementById('result-score').textContent=`${d.score}/${d.total}`;
        document.getElementById('result-copy').textContent=`You answered ${d.score} of ${d.total} correctly (${d.percent}%). Review the explanations below to reinforce your learning.`;
        document.getElementById('review-list').innerHTML=d.review.map((x,i)=>`<div class="review-item ${x.is_correct?'correct':'incorrect'}"><div class="review-head"><b>${i+1}. ${esc(x.q)}</b><span>${x.is_correct?'✓ Correct':'↻ Review'}</span></div><p>Your answer: ${esc(x.chosen)}</p><p>Correct answer: <b>${esc(x.correct)}</b></p><small>${esc(x.why)}</small></div>`).join('');
      }catch(e){alert(e.message);}finally{btn.disabled=false;}
    });
    document.getElementById('retry-quiz').addEventListener('click',()=>{result.hidden=true;picker.hidden=false;});
  }
});
