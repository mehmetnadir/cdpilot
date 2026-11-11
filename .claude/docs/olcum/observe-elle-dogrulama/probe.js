(()=>{const vis=e=>{const r=e.getBoundingClientRect();const cs=getComputedStyle(e);return r.width>0&&r.height>0&&cs.visibility!=='hidden'&&cs.display!=='none'};
const sel='a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=link],[role=tab],[role=menuitem],[role=checkbox],[role=radio],[role=switch],[role=option],[role=combobox],[role=textbox],[onclick],[tabindex]:not([tabindex="-1"]),[contenteditable=true]';
const out=[];const seen=new Set();
const nm=e=>(e.getAttribute('aria-label')||e.innerText||e.getAttribute('title')||e.getAttribute('alt')||e.value||e.getAttribute('placeholder')||'').replace(/\s+/g,' ').trim().slice(0,60);
for(const e of document.querySelectorAll(sel)){if(!vis(e))continue;seen.add(e);out.push({k:'native',tag:e.tagName,role:e.getAttribute('role')||'',name:nm(e),href:(e.getAttribute('href')||'').slice(0,50)})}
for(const e of document.querySelectorAll('body *')){if(seen.has(e)||!vis(e))continue;const cs=getComputedStyle(e);if(cs.cursor!=='pointer')continue;if(e.closest('a[href],button,[role=button],[role=link],summary,label,select'))continue;const p=e.parentElement;if(p&&getComputedStyle(p).cursor==='pointer'&&!seen.has(p)&&!p.matches('body'))continue;out.push({k:'pointer',tag:e.tagName,role:e.getAttribute('role')||'',name:nm(e),href:''})}
return JSON.stringify(out)})()
