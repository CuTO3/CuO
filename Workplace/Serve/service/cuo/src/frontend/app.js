'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths = {overview:'<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',log:'<rect x="5" y="3" width="14" height="18" rx="3"/><path d="M9 8h6M9 12h6M9 16h4"/>',members:'<circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6M18 14a5 5 0 0 1 3 5"/>',summaries:'<path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-2H4zM13 7a3 3 0 0 1 3-3h5v15h-4a4 4 0 0 0-4 2"/>',divinations:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>',messages:'<path d="M21 11a9 9 0 0 1-9 9H4l-2 2V11a9 9 0 0 1 19 0Z"/><path d="M7 10h10M7 14h6"/>',settings:'<path d="M4 7h5m4 0h7M4 17h9m4 0h3"/><circle cx="11" cy="7" r="2"/><circle cx="15" cy="17" r="2"/>',images:'<rect x="3" y="3" width="18" height="18" rx="4"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m4 17 5-5 4 4 3-3 5 5"/>',check:'<path d="m5 12 4 4L19 6"/>',arrow:'<path d="M5 12h14M14 7l5 5-5 5"/>'};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.log}</svg>`;
const pages = {overview:['总览','AT A GLANCE','每一刻，都在掌握。','让繁杂留在幕后，让日常轻盈有序。'],images:['图片标注','VISUAL LIBRARY','看清每一张，校准每一处。','查看原图、修正识别，让每一条图片描述都更准确。'],log:['任务记录','ACTIVITY','每一次响应，都有迹可循。','查看执行进度，追踪异常与消息送达。'],members:['群成员','PEOPLE','熟悉的名字，新的故事。','查看成员资料与福缘，维护专属显示名称。'],summaries:['众声录','COLLECTIONS','把热闹，留成记忆。','按时间回看群聊总结，重新发现值得记住的瞬间。'],divinations:['周易','DAILY INSIGHTS','一日一卦，一点启发。','查看每日占卜、解读与福缘变化。'],settings:['偏好设置','PREFERENCES','恰到好处，刚好适合。','调整运行参数，让氧化铜以你的节奏工作。']};
const state = {page:'overview',gid:'',rows:[],settings:null,epoch:0,authenticated:false};
const labels = {completed:'已完成',pending:'等待中',running:'处理中',failed:'失败',needs_review:'待处理',settled:'已结算',generating:'生成中',conversation:'清谈录',summary:'众声录',divine:'周易',memento:'鸿爪录',message:'群消息',admin_update:'管理操作',initialize_day:'日初始化',archive_day:'日归档',media_describe:'图片理解'};
const format = n => Number(n || 0).toLocaleString('zh-CN');
const date = value => value ? new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '—';
const badge = value => `<span class="badge ${esc(value)}">${esc(labels[value] || value || '—')}</span>`;
function toast(message){$('#toast').textContent=message;$('#toast').classList.remove('hidden');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').classList.add('hidden'),4500);}
function showLogin(){clearImageEditor();state.authenticated=false;state.epoch++;$('#shell').classList.add('hidden');$('#login').classList.remove('hidden');}
async function api(path,options={}){const response=await fetch(path,{...options,headers:{'Content-Type':'application/json','X-Cuo-Request':'console',...options.headers},signal:AbortSignal.timeout(15000)});let data;try{data=await response.json();}catch{data={};}if(!response.ok){if(response.status===401&&!path.endsWith('/login'))showLogin();throw new Error(typeof data.detail==='string'?data.detail:`请求失败（${response.status}）`);}return data;}
$('#nav').innerHTML=Object.entries(pages).map(([key,value])=>`${key==='settings'?'<div class="nav-divider"></div>':''}<a href="#${key}" data-page="${key}">${icon(key)}<span>${value[0]}</span></a>`).join('');
$('#login-form').addEventListener('submit',async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;$('#login-error').textContent='';try{await api('/console/api/login',{method:'POST',body:JSON.stringify({token:$('#token').value})});$('#token').value='';await start();}catch(error){$('#login-error').textContent=error.message;}finally{button.disabled=false;}});
$('#logout').onclick=async()=>{if(!canLeaveImages())return;try{await api('/console/api/logout',{method:'POST'});showLogin();}catch(error){toast(error.message);}};
$('#refresh').onclick=()=>load();
$('#group').onchange=()=>{if(!canLeaveImages()){$('#group').value=state.gid;return;}imageUI.dirty=false;state.gid=$('#group').value;load();};
window.addEventListener('hashchange',()=>{if(state.authenticated)load();});
$('#close-dialog').onclick=()=>$('#detail').close();
function notice(message){$('#notice').textContent=message;$('#notice').classList.toggle('hidden',!message);}
async function start(){const groups=await api('/admin/groups');state.authenticated=true;state.gid=groups.groups.includes(state.gid)?state.gid:groups.groups[0];$('#group').innerHTML=groups.groups.map(g=>`<option value="${esc(g)}">群 ${esc(g)}</option>`).join('');$('#group').value=state.gid;$('#login').classList.add('hidden');$('#shell').classList.remove('hidden');await load();}
async function load(){if(!canLeaveImages()){history.replaceState(null,'','#images');return;}clearImageEditor();const epoch=++state.epoch;state.page=Object.hasOwn(pages,location.hash.slice(1))?location.hash.slice(1):'overview';const p=pages[state.page];$('#breadcrumb').textContent=p[0];$('#page-eyebrow').textContent=p[1];$('#page-title').textContent=p[2];$('#page-subtitle').textContent=p[3];document.querySelectorAll('nav a').forEach(a=>{a.classList.toggle('active',a.dataset.page===state.page);if(a.dataset.page===state.page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});notice('');$('#content').innerHTML='<div class="loading">正在同步服务器数据</div>';$('#refresh').disabled=true;try{const ready=await api('/ready');if(epoch!==state.epoch)return;$('#connection-dot').classList.toggle('online',ready.ready&&ready.onebot_connected);$('#connection-text').textContent=ready.onebot_connected?'机器人已连接':'机器人未连接';if(state.page==='overview'){const [data,rows]=await Promise.all([api(`/console/api/overview/${state.gid}`),api(`/admin/${state.gid}/log?limit=6`)]);if(epoch!==state.epoch)return;state.rows=rows;renderOverview(data);}else if(state.page==='images'){const data=await api(`/console/api/images/${state.gid}`);if(epoch!==state.epoch)return;renderImages(data);}else if(state.page==='settings'){const data=await api('/console/api/configuration');if(epoch!==state.epoch)return;state.settings=data;renderSettings();}else{const rows=await api(`/admin/${state.gid}/${state.page}?limit=500`);if(epoch!==state.epoch)return;state.rows=rows;renderRecords();}$('#updated').textContent='更新于 '+new Date().toLocaleTimeString('zh-CN',{hour12:false});}catch(error){if(epoch===state.epoch){notice(error.message);$('#content').innerHTML='<div class="card empty">暂时无法读取数据。请检查连接后，点击右上角刷新。</div>';$('#connection-dot').classList.remove('online');$('#connection-text').textContent='连接异常';}}finally{if(epoch===state.epoch)$('#refresh').disabled=false;}}
function renderOverview(data){const t=data.tasks;const waiting=(t.failed||0)+(t.needs_review||0);const healthy=data.ready&&data.connected;const stats=[['已接收消息',data.counts.messages,'messages','持久化消息总量'],['群成员',data.counts.members,'members','已记录的成员'],['已完成任务',t.completed,'check','历史累计完成'],['需要关注',waiting,'log',waiting?'异常任务等待检查':'当前没有异常任务']];const days=Array.from({length:7},(_,i)=>{const d=new Date(Date.now()-(6-i)*86400000);return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);});const max=Math.max(1,...data.daily.map(d=>d.n));
$('#content').innerHTML=`<section class="hero"><div class="hero-main"><div class="hero-icon">${icon(healthy?'check':'log')}</div><div><h2>${healthy?'一切就绪，静候下一段对话。':'连接需要留意。'}</h2><p>${healthy?'服务与机器人连接正常，消息正在有序接收。':'后端或机器人尚未就绪，请检查运行状态。'}</p></div></div><div class="hero-right"><span class="pill"><i class="dot ${healthy?'online':''}"></i>${healthy?'运行正常':'待检查'}</span></div><span class="hero-watermark">CuO</span></section><section class="stats">${stats.map(([name,n,ic,hint])=>`<div class="stat"><div class="stat-top"><span>${name}</span>${icon(ic)}</div><div class="stat-value">${format(n)}</div><div class="stat-bottom">${hint}</div></div>`).join('')}</section><section class="dashboard-grid"><div class="card"><div class="card-head"><div><h2>对话的节奏</h2><p>最近七个业务日 · 消息数量</p></div><span class="pill">近 7 天</span></div><div class="chart-area"><div class="chart">${days.map(day=>{const n=data.daily.find(x=>x.day===day)?.n||0;return `<div class="bar-wrap"><span class="bar-count">${format(n)}</span><div class="bar" data-height="${Math.max(2,Math.round(n/max*115))}" title="${day} · ${n} 条消息"></div></div>`;}).join('')}</div><div class="chart-labels">${days.map(d=>`<span>${esc(d.slice(5).replace('-','/'))}</span>`).join('')}</div></div></div><div class="card"><div class="card-head"><div><h2>能力一览</h2><p>小小的日常，也值得认真对待</p></div>${icon(divIcon())}</div><div class="module-list">${[['messages','清谈录','陪伴与闲聊',data.model],['summaries','众声录','群聊记忆',`${format(data.counts.summaries)} 篇总结`],['divinations','周易','每日灵感',`${format(data.counts.divinations)} 次记录`],['members','鸿爪录','名字的变迁','成员档案']].map(([ic,name,desc,status])=>`<div class="module"><div class="module-icon">${icon(ic)}</div><div><strong>${name}</strong><p>${desc}</p></div><span class="module-status">${esc(status)}</span></div>`).join('')}</div></div></section><section class="card"><div class="card-head"><div><h2>最近的动态</h2><p>后台执行记录 · 收件队列 ${format(data.inbound)}</p></div><a href="#log" class="text-button">全部记录 ↗</a></div>${taskTable(state.rows)}</section>`;
document.querySelectorAll('[data-height]').forEach(el=>{el.style.height=el.dataset.height+'px';});bindRowActions();}
function divIcon(){return 'divinations';}
function empty(text='这里还很安静。新的记录到来后，会显示在这里。'){return `<div class="empty">${icon('summaries')}${text}</div>`;}
function taskTable(rows){if(!rows.length)return empty();return `<div class="table-scroll"><table><thead><tr><th>任务</th><th>发起时间</th><th>执行状态</th><th>阶段</th><th></th></tr></thead><tbody>${rows.map(row=>{const r=row.record;return `<tr><td><div class="cell-main">${esc(labels[r.params?._opt]||labels[r.request_type]||r.request_type)}<span class="secondary">${esc(r.task_id?.slice(0,8))}</span></div></td><td>${date(r.created_at)}</td><td>${badge(r.status)}</td><td>${esc(r.step)}</td><td><button class="table-action" data-detail="${state.rows.indexOf(row)}">查看 ↗</button></td></tr>`;}).join('')}</tbody></table></div>`;}
function renderRecords(){const name=pages[state.page][0];$('#content').innerHTML=`<section class="card"><div class="card-head"><div><h2>${name}</h2><p>当前群组 · ${esc(state.gid)}</p></div><span class="pill">${state.rows.length} 条已载入</span></div><div class="toolbar"><input id="search" class="search" aria-label="搜索记录" placeholder="搜索当前载入的记录…">${state.page==='log'?'<select id="status-filter" class="filter" aria-label="按状态筛选"><option value="">全部状态</option><option value="needs_review">待处理</option><option value="failed">失败</option><option value="pending">等待中</option><option value="running">处理中</option><option value="completed">已完成</option></select>':''}<button id="export" class="table-action">导出 JSON ↓</button></div><div id="records"></div><div class="table-note">最多显示最近 500 条 · 搜索和导出仅作用于当前载入的记录 · 时间为北京时间</div></section>`;$('#search').oninput=filterRecords;if($('#status-filter'))$('#status-filter').onchange=filterRecords;$('#export').onclick=()=>{const blob=new Blob([JSON.stringify(filteredRows().map(r=>r.record),null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`cuo-${state.page}-${state.gid}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};filterRecords();}
function filteredRows(){const q=$('#search').value.trim().toLowerCase();const status=$('#status-filter')?.value;return state.rows.filter(r=>(!q||(JSON.stringify(r.record)+' '+(labels[r.record.request_type]||'')+' '+(labels[r.record.status]||'')).toLowerCase().includes(q))&&(!status||r.record.status===status));}
function filterRecords(){const rows=filteredRows();if(!rows.length){$('#records').innerHTML=empty($('#search').value?'没有找到匹配的记录。':'这里还没有记录。');return;}if(state.page==='log'){$('#records').innerHTML=taskTable(rows);bindRowActions();return;}const headers={members:['成员','QQ 号','显示名称','福缘','最近更新',''],messages:['内容','发送者','QQ 号','时间',''],summaries:['总结内容','业务日期','生成时间',''],divinations:['占卜内容','成员','业务日期','状态','']}[state.page];$('#records').innerHTML=`<div class="table-scroll"><table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>{const r=row.record;const index=state.rows.indexOf(row);let cells;if(state.page==='members')cells=[r.nickname||'未命名',r.user_id,r.display_name||'—',r.fortune,date(r.updated_at)];else if(state.page==='messages')cells=[r.text||'媒体消息',r.nickname||'—',r.user_id,date(r.sent_at)];else if(state.page==='summaries')cells=[r.content,r.business_date,date(r.created_at)];else cells=[r.content||r.keyword||'生成中',r.user_id,r.business_date,labels[r.status]||r.status];return `<tr>${cells.map(c=>`<td><div class="cell-main">${esc(c)}</div></td>`).join('')}<td><div class="member-actions"><button class="table-action" data-detail="${index}">${state.page==='members'?'管理':'查看'} ↗</button>${state.page==='members'?`<button class="table-action" data-fortune="${index}">改福缘 ↗</button>`:''}</div></td></tr>`;}).join('')}</tbody></table></div>`;bindRowActions();}
function bindRowActions(){document.querySelectorAll('[data-detail]').forEach(b=>b.onclick=()=>showDetail(Number(b.dataset.detail)));document.querySelectorAll('[data-fortune]').forEach(b=>b.onclick=()=>showFortune(Number(b.dataset.fortune)));}
let fortuneEdit=null;
function showFortune(index){
 const row=state.rows[index];
 fortuneEdit={row,gid:state.gid,busy:false,pending:false};
 $('#fortune-member').textContent=`${row.record.display_name||row.record.nickname||'未命名'} · ${row.record.user_id}`;
 $('#fortune-current').textContent=format(row.record.fortune);
 $('#fortune-value').value=row.record.fortune;
 $('#fortune-status').textContent='支持正负整数。保存后会显示执行结果。';
 $('#fortune-form').querySelectorAll('button,input').forEach(el=>el.disabled=false);
 $('#close-fortune').disabled=false;
 updateFortuneChange();
 $('#fortune-dialog').showModal();
 $('#fortune-value').focus();
 $('#fortune-value').select();
}
function fortuneValue(){const raw=$('#fortune-value').value.trim();const value=Number(raw);return raw&&Number.isSafeInteger(value)?value:null;}
function updateFortuneChange(){
 const value=fortuneValue();const before=fortuneEdit?.row.record.fortune;
 $('#fortune-change').textContent=value===null?'请输入有效的整数。':`${format(before)} → ${format(value)}`;
 $('#save-fortune').disabled=!fortuneEdit||fortuneEdit.busy||fortuneEdit.pending||value===null||value===before;
}
$('#fortune-value').oninput=updateFortuneChange;
document.querySelectorAll('[data-fortune-step]').forEach(button=>button.onclick=()=>{
 const value=fortuneValue();if(value===null)return;
 const next=value+Number(button.dataset.fortuneStep);if(!Number.isSafeInteger(next))return;
 $('#fortune-value').value=next;updateFortuneChange();
});
$('#close-fortune').onclick=()=>{if(!fortuneEdit?.busy)$('#fortune-dialog').close();};
$('#fortune-dialog').addEventListener('cancel',event=>{if(fortuneEdit?.busy)event.preventDefault();});
$('#fortune-form').onsubmit=async event=>{
 event.preventDefault();const edit=fortuneEdit;const value=fortuneValue();
 if(!edit||edit.busy||edit.pending||value===null||value===edit.row.record.fortune)return;
 edit.busy=true;
 $('#fortune-form').querySelectorAll('button,input').forEach(el=>el.disabled=true);
 $('#close-fortune').disabled=true;
 $('#fortune-status').textContent='正在提交修改…';
 let taskId;
 try{
  const response=await api(`/admin/${edit.gid}/commands`,{method:'POST',body:JSON.stringify({operation:'fortune',user_id:edit.row.record.user_id,fortune:value,expected_version:edit.row.version})});
  taskId=response.task_id;edit.pending=true;
  $('#fortune-status').textContent='已入队，正在等待执行结果…';
  for(let attempt=0;attempt<15;attempt++){
   const {record}=await api(`/admin/${edit.gid}/commands/${taskId}`);
   if(record.business_status==='completed'){
    if(record.result?.status==='ok'){
     $('#fortune-dialog').close();toast(`福缘已修改：${format(record.result.fortune_before)} → ${format(record.result.fortune_after)}`);
     if(state.authenticated&&state.gid===edit.gid&&state.page==='members')await load();
    }else{
     $('#fortune-status').textContent=record.result?.error_code==='version_conflict'?'成员数据已变化，本次未修改。请关闭后重新打开。':'修改未成功，请在任务记录查看详情。';
     if(state.authenticated&&state.gid===edit.gid&&state.page==='members')await load();
    }
    return;
   }
   if(['failed','needs_review'].includes(record.status)){$('#fortune-status').textContent='修改未完成，请在任务记录查看详情。';return;}
   await new Promise(resolve=>setTimeout(resolve,1000));
  }
  $('#fortune-status').textContent=`任务 ${taskId.slice(0,8)} 仍在队列中，请稍后在任务记录确认。`;
 }catch(error){
  $('#fortune-status').textContent=taskId?`任务 ${taskId.slice(0,8)} 已提交，暂时无法确认结果，请在任务记录查看。`:error.message;
 }finally{
  edit.busy=false;$('#close-fortune').disabled=false;
  if(!edit.pending)$('#fortune-form').querySelectorAll('button,input').forEach(el=>el.disabled=false);
  updateFortuneChange();
 }
};
function showDetail(index){const row=state.rows[index],r=row.record;const member=state.page==='members';$('#detail-title').textContent=member?'成员显示名称':'记录详情';$('#detail-body').innerHTML=member?`<p>${esc(r.nickname)} · ${esc(r.user_id)}<br>显示名称用于管理侧标识，留空将恢复默认名称。</p><label for="display-name" class="hidden">显示名称</label><input id="display-name" maxlength="100" value="${esc(r.display_name||'')}" placeholder="输入显示名称"><p>修改通过任务队列执行，提交后可在任务记录查看结果。</p><div class="detail-actions"><button id="save-member" class="primary">提交修改</button></div>`:`<pre>${esc(JSON.stringify(r,null,2))}</pre><p>记录只读。含有消息送达结果的异常任务，需要先核实是否已经发送。</p>`;$('#detail').showModal();if(member)$('#save-member').onclick=async e=>{e.target.disabled=true;try{const response=await api(`/admin/${state.gid}/commands`,{method:'POST',body:JSON.stringify({operation:'display_name',user_id:r.user_id,display_name:$('#display-name').value.trim()||null,expected_version:row.version})});$('#detail').close();toast(`修改已入队 · ${response.task_id.slice(0,8)}，请在任务记录确认结果`);}catch(error){toast(error.message);}finally{e.target.disabled=false;}};}
function renderSettings(){
  const modules=state.settings.modules;
  $('#content').innerHTML='<section class="card"><div class="card-head"><h2>模块配置</h2></div><div class="form-body"><select id="config-module">'+Object.entries(modules).map(([name,spec])=>`<option value="${esc(name)}">${esc(spec.source)}</option>`).join('')+'</select><p>保存后需重启服务。敏感字段不回显，留空表示保留原值。</p><form id="module-config-form"></form></div></section>';
  let current=null, activeName=null, revision=0;
  async function select(){
    const token=++revision;const name=$('#config-module').value;
    $('#module-config-form').innerHTML='正在加载配置…';current=null;
    try{
      const data=await api('/console/api/configuration/'+encodeURIComponent(name));
      if(token!==revision)return;current=data;activeName=name;
      $('#module-config-form').innerHTML=Object.entries(data.fields).map(([key,f])=>{
        const value=f.sensitive?'':data.values[key];
        const input=f.type==='bool'?`<select name="${esc(key)}"><option value="true" ${value?'selected':''}>启用</option><option value="false" ${!value?'selected':''}>关闭</option></select>`:
          f.type==='table'||f.type==='strings'?`<textarea name="${esc(key)}" rows="5" placeholder="${f.sensitive?'留空保留原值':''}">${esc(f.sensitive?'':JSON.stringify(value,null,2))}</textarea>`:
          `<input name="${esc(key)}" type="${f.sensitive?'password':f.type==='int'||f.type==='float'?'number':'text'}" step="any" autocomplete="off" value="${esc(value)}" placeholder="${f.sensitive?(data.configured[key]?'已配置；留空保留':'尚未配置'):''}">`;
        return `<div class="form-row"><label>${esc(f.description)}<small>${esc(key)}</small></label>${input}</div>`;
      }).join('')+'<button class="primary" type="submit">保存配置</button>';
    }catch(error){if(token===revision)$('#module-config-form').textContent=error.message;}
  }
  $('#config-module').onchange=select;
  $('#module-config-form').onsubmit=async event=>{
    event.preventDefault();if(!current)return;
    const values={};const button=event.submitter;const name=activeName;const version=current.version;
    try{
      for(const [key,f] of Object.entries(current.fields)){
        const raw=event.target.elements.namedItem(key).value;
        if(f.sensitive&&raw==='')continue;
        values[key]=f.type==='bool'?raw==='true':f.type==='int'||f.type==='float'?Number(raw):f.type==='table'||f.type==='strings'?JSON.parse(raw):raw;
      }
      button.disabled=true;
      await api('/console/api/configuration/'+encodeURIComponent(name),{method:'PUT',body:JSON.stringify({values,version})});
      toast('已保存，重启服务后生效');await select();
    }catch(error){toast(error.message);}finally{if(button.isConnected)button.disabled=false;}
  };
  select();
}

start().catch(error=>{showLogin();if(!error.message.includes('登录')&&!error.message.includes('authentication'))$('#login-error').textContent=error.message;});
