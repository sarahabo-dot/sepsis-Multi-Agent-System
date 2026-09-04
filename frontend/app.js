const API = window.SEPSIS_API_BASE || '';
const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];

let AUTH_TOKEN = localStorage.getItem('sepsis_token') || null;
let AUTH_USERNAME = localStorage.getItem('sepsis_username') || null;

async function api(path, options={}){
  const headers={'Content-Type':'application/json',...(options.headers||{})};
  if(AUTH_TOKEN) headers['Authorization']='Bearer '+AUTH_TOKEN;
  const res=await fetch(API+path,{headers,...options});
  const text=await res.text(); let data={}; try{data=JSON.parse(text)}catch{data={detail:text}};
  if(!res.ok){
    if(res.status===401){ doLogout(false); }
    throw new Error(data.detail||`HTTP ${res.status}`);
  }
  return data;
}

function showApp(){
  $('#loginScreen').classList.add('hidden');
  $('#appShell').classList.remove('hidden');
  $('#sidebarUsername').textContent=AUTH_USERNAME||'—';
  api('/guidelines/status').then(updateGuidelinesBadge).catch(()=>{});
}
function showLogin(){
  $('#appShell').classList.add('hidden');
  $('#loginScreen').classList.remove('hidden');
}
function doLogout(callServer=true){
  const token=AUTH_TOKEN;
  AUTH_TOKEN=null; AUTH_USERNAME=null;
  localStorage.removeItem('sepsis_token'); localStorage.removeItem('sepsis_username');
  showLogin();
  if(callServer && token){
    fetch(API+'/auth/logout',{method:'POST',headers:{'Authorization':'Bearer '+token}}).catch(()=>{});
  }
}
$('#logoutBtn').addEventListener('click',()=>doLogout(true));

let FIRST_RUN=false;
async function initAuth(){
  if(AUTH_TOKEN){
    try{ const me=await api('/auth/me'); AUTH_USERNAME=me.username; showApp(); return; }
    catch{ /* token invalid/expired — fall through to login */ }
  }
  showLogin();
  try{
    const status=await fetch(API+'/auth/status').then(r=>r.json());
    FIRST_RUN=!status.has_users;
    $('#firstRunNotice').classList.toggle('hidden',!FIRST_RUN);
    $('#loginBtnLabel').textContent=FIRST_RUN?'Create account':'Log in';
  }catch{ /* if this fails, login will just surface the error on submit */ }
}

$('#loginForm').addEventListener('submit', async e=>{
  e.preventDefault();
  const form=e.currentTarget; const err=$('#loginError'); err.classList.add('hidden');
  const username=form.elements.username.value.trim(); const password=form.elements.password.value;
  const btn=$('.primary',form); btn.disabled=true;
  try{
    const path=FIRST_RUN?'/auth/bootstrap':'/auth/login';
    const res=await fetch(API+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});
    const data=await res.json();
    if(!res.ok) throw new Error(data.detail||'Login failed');
    AUTH_TOKEN=data.token; AUTH_USERNAME=data.username;
    localStorage.setItem('sepsis_token',AUTH_TOKEN); localStorage.setItem('sepsis_username',AUTH_USERNAME);
    showApp();
  }catch(ex){
    err.textContent=ex.message; err.classList.remove('hidden');
  }finally{
    btn.disabled=false;
  }
});

initAuth();

function showView(name){
  $$('.view').forEach(v=>v.classList.toggle('active',v.id===name));
  $$('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.view===name));
  const titles={assessment:'Clinical Assessment',governance:'Governance',memory:'Memory & Analytics',architecture:'Five-Agent System',guidelines:'Antibiotic Guidelines'};
  $('#pageTitle').textContent=titles[name]||'Clinical Assessment';
  if(name==='memory') loadAnalytics();
  if(name==='governance') loadAudit();
  if(name==='guidelines') loadGuidelines();
}
$$('.nav-item').forEach(b=>b.addEventListener('click',()=>showView(b.dataset.view)));

function optionalNumber(form,name){const v=form.elements[name].value; return v===''?null:Number(v)}
function checked(form,name){return [...form.querySelectorAll(`input[name="${name}"]:checked`)].map(x=>x.value)}

$('#assessmentForm').addEventListener('submit',async e=>{
  e.preventDefault();
  const form=e.currentTarget; const btn=$('.primary',form); const err=$('#assessmentError');
  err.classList.add('hidden'); btn.disabled=true; btn.querySelector('span').textContent='Running governed assessment…';
  const pressorDrug=form.elements.pressor_drug.value; const pressorDose=optionalNumber(form,'pressor_dose');
  if(pressorDrug!=='none' && pressorDose===null){
    err.textContent='Vasopressor dose (mcg/kg/min) is required when a vasopressor is selected — otherwise the cardiovascular SOFA component will silently score as if no vasopressor were running.';
    err.classList.remove('hidden'); btn.disabled=false; btn.querySelector('span').textContent='Run governed assessment';
    return;
  }
  const payload={case_id:form.elements.case_id.value.trim(),patient_id:form.elements.patient_id.value.trim(),severity:form.elements.severity.value,suspected_source:form.elements.suspected_source.value,
    pao2_fio2:optionalNumber(form,'pao2_fio2'),platelets:optionalNumber(form,'platelets'),bilirubin:optionalNumber(form,'bilirubin'),map_mmhg:optionalNumber(form,'map_mmhg'),gcs:optionalNumber(form,'gcs'),creatinine:optionalNumber(form,'creatinine'),urine_output_value:optionalNumber(form,'urine_output_value'),urine_output_unit:form.elements.urine_output_unit.value,weight_kg:optionalNumber(form,'weight_kg'),
    pressor_drug:pressorDrug,pressor_dose:pressorDose,mdr_risk_factors:checked(form,'mdr'),mrsa_risk_factors:checked(form,'mrsa'),anaerobic_risk_factors:checked(form,'anaerobic'),fungal_risk_factors:checked(form,'fungal'),documented_allergies:form.elements.allergies.value.split(';').map(x=>x.trim()).filter(Boolean)};
  try{const data=await api('/assess',{method:'POST',body:JSON.stringify(payload)}); renderResult(data); document.querySelector('[data-view="assessment"]').click(); loadAudit();}
  catch(ex){err.textContent=ex.message;err.classList.remove('hidden')}
  finally{btn.disabled=false;btn.querySelector('span').textContent='Run governed assessment'}
});

const SOFA_LABELS={respiratory:'Respiratory (PaO₂/FiO₂)',coagulation:'Coagulation (Platelets)',liver:'Liver (Bilirubin)',cardiovascular:'Cardiovascular (MAP/Vasopressor)',cns:'CNS (GCS)',renal:'Renal (Creatinine/Urine)'};

function renderResult(data){
  $('#resultPanel').classList.remove('hidden');
  const sofa=data.sofa||{}; $('#sofaScore').textContent=sofa.total ?? sofa.score ?? '—';
  const urineEl=$('#urineNote');
  if(data.urine_output_error){urineEl.textContent='⚠ '+data.urine_output_error;urineEl.classList.remove('hidden')}
  else if(data.pressor_error){urineEl.textContent='⚠ '+data.pressor_error;urineEl.classList.remove('hidden')}
  else if(data.urine_output_note){urineEl.textContent=data.urine_output_note;urineEl.classList.remove('hidden')}
  else{urineEl.classList.add('hidden');urineEl.textContent=''}

  const components=sofa.components||{};
  $('#sofaBreakdown').innerHTML=Object.entries(SOFA_LABELS).map(([key,label])=>{
    const val=components[key]; if(val===undefined) return '';
    const pct=Math.min(100,(val/4)*100);
    return `<div class="sofa-row"><span>${label}</span><b>${val}</b><span class="sofa-bar ${val>=3?'high':''}"><span style="width:${pct}%"></span></span></div>`;
  }).join('');

  const g=data.governance; const pill=$('#resultStatus'); pill.className='status-pill '+(g?.status?.toLowerCase()||''); pill.textContent=g?.status||data.antibiotic_error||'NO DECISION';
  const ab=$('#antibioticResult'); const a=data.antibiotic;
  if(a){const regimen=a.recommended_regimen||[];ab.innerHTML=`<div><b>Timing target:</b> ${a.timing_target_hours??'—'} h</div>${regimen.map(r=>`<div class="drug"><span><b>${escapeHtml(r.drug_class||'Unclassified')}</b><br><small>suggested agent: ${escapeHtml(r.drug_name||'—')}</small></span><span>${escapeHtml(r.dose||'')} ${escapeHtml(r.route||'')} ${escapeHtml(r.frequency||'')}</span></div>`).join('')||'<div>No regimen returned.</div>'}`}
  else ab.innerHTML=`<div class="alert error">${escapeHtml(data.antibiotic_error||'No trusted antibiotic output')}</div>`;
  $('#governanceResult').innerHTML=g?`<div><b>Status:</b> ${escapeHtml(g.status)}</div><div><b>KB:</b> ${escapeHtml(g.kb_version||'—')}</div><div><b>Warnings:</b> ${g.warnings?.length?escapeHtml(g.warnings.join('; ')):'None'}</div><div><b>Violations:</b> ${g.violations?.length?escapeHtml(g.violations.join('; ')):'None'}</div>`:'No governance result.';

  // Plain-language summary — this replaces the raw JSON as the primary view.
  const sum=$('#readableSummary');
  const sections=[];
  sections.push(`<div class="rs-section"><h4>Case</h4><p>${escapeHtml(data.case_id||'—')} · SOFA total ${sofa.total??'—'} (${sofa.completeness!=null?Math.round(sofa.completeness*100)+'% of inputs provided':'completeness unknown'})</p></div>`);
  if(a){
    const mods=a.applied_modifiers||[];
    sections.push(`<div class="rs-section"><h4>Why this antibiotic recommendation</h4><p>${escapeHtml(a.rationale||'No rationale returned.')}</p>${mods.length?`<ul>${mods.map(m=>`<li>${escapeHtml(m.action_taken||m.modifier_type||'')}${m.requires_confirmation?' — requires physician confirmation':''}</li>`).join('')}</ul>`:''}</div>`);
    if(a.reassessment_due_at) sections.push(`<div class="rs-section"><h4>Reassessment</h4><p>Empirical regimen — reassess against culture results by <b>${escapeHtml(a.reassessment_due_at)}</b> if no culture result has come back yet.</p></div>`);
    if((a.missing_inputs||[]).length) sections.push(`<div class="rs-section"><h4>Missing inputs</h4><ul>${a.missing_inputs.map(m=>`<li>${escapeHtml(m)}</li>`).join('')}</ul></div>`);
    if((a.warnings||[]).length) sections.push(`<div class="rs-section"><h4>Warnings</h4><ul>${a.warnings.map(w=>`<li>${escapeHtml(w)}</li>`).join('')}</ul></div>`);
  }
  sum.innerHTML=sections.join('') || '<p class="rs-empty">No details to show.</p>';

  $('#rawResult').textContent=JSON.stringify(data,null,2);
}

async function loadAnalytics(){
  try{const d=await api('/analytics');$('#analyticsRaw').textContent=JSON.stringify(d,null,2);const values=extractAnalytics(d);$('#analyticsCards').innerHTML=values.map(x=>`<div class="stat-card"><span>${x[0]}</span><strong>${x[1]}</strong></div>`).join('')}
  catch(e){$('#analyticsRaw').textContent='Analytics unavailable: '+e.message}
}
function extractAnalytics(d){
  const n=d.total_cases??d.case_count??d.cases??'—', pass=d.governance_pass??d.passed??'—', block=d.governance_blocked??d.blocked??'—', sofa=d.mean_sofa??d.average_sofa??'—';
  return [['Cases',n],['Governance pass',pass],['Blocked',block],['Mean SOFA',sofa]];
}
$('#refreshAnalytics').addEventListener('click',loadAnalytics);

async function health(){try{const d=await api('/health');$('#healthStatus').textContent='SYSTEM — ONLINE';$('#kbVersion').textContent=`KB — ${d.active_kb_version||'none'}`}catch{$('#healthStatus').textContent='SYSTEM — OFFLINE';$('#kbVersion').textContent='KB — unavailable'}}
function escapeHtml(s){return String(s).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
health();

function parseSensitivities(text){
  const out={};
  text.split('\n').forEach(line=>{
    const m=line.split(':');
    if(m.length>=2){const drug=m[0].trim(); const rating=m.slice(1).join(':').trim().toUpperCase(); if(drug && ['S','I','R'].includes(rating)) out[drug]=rating;}
  });
  return out;
}

$('#deescalateForm').addEventListener('submit', async e=>{
  e.preventDefault();
  const form=e.currentTarget; const btn=$('.primary',form); const err=$('#deescalateError'); const resultEl=$('#deescalateResult');
  err.classList.add('hidden'); resultEl.classList.add('hidden'); btn.disabled=true; btn.querySelector('span').textContent='Evaluating…';
  try{
    const sensitivities=parseSensitivities(form.elements.de_sensitivities.value);
    if(Object.keys(sensitivities).length===0) throw new Error('Enter at least one "Drug: S/I/R" line.');
    const payload={
      case_id: form.elements.de_case_id.value.trim(),
      severity: form.elements.de_severity.value,
      suspected_source: form.elements.de_suspected_source.value,
      current_regimen_drug_names: form.elements.de_current_regimen.value.split(',').map(x=>x.trim()).filter(Boolean),
      culture: {organism: form.elements.de_organism.value.trim(), sensitivities},
      creatinine: form.elements.de_creatinine.value===''?null:Number(form.elements.de_creatinine.value),
      documented_allergies: form.elements.de_allergies.value.split(';').map(x=>x.trim()).filter(Boolean),
    };
    const data=await api('/deescalate',{method:'POST',body:JSON.stringify(payload)});
    // data.deescalation is the whole AntibioticResponse; the actual
    // DeescalationAdvice (resistant_alert, narrower_regimen, etc.) is
    // nested one level deeper, under its own `.deescalation` field.
    const outer=data.deescalation; const d=outer ? outer.deescalation : null; const g=data.governance;
    resultEl.classList.remove('hidden');
    const govLine = g ? `<div class="rs-section"><span class="status-pill ${(g.status||'').toLowerCase()}">${escapeHtml(g.status||'')}</span> <small style="color:var(--muted)">KB ${escapeHtml(g.kb_version||'—')}</small></div>` : '';
    let body;
    if(!d){
      body = `<div class="alert error">${escapeHtml(data.error||'No trusted de-escalation output — governance blocked or agent error.')}</div>`;
    } else if(d.resistant_alert){
      body = `<div class="alert error"><b>⚠ RESISTANT ALERT</b><br>The organism is not covered by any drug in the current regimen. Manual antibiotic selection is required immediately.</div>`;
    } else {
      const narrow=(d.narrower_regimen||[]);
      body = narrow.length
        ? `<div class="rs-section"><h4>Narrower option available</h4>${narrow.map(r=>`<div class="drug"><span><b>${escapeHtml(r.drug_class||'Unclassified')}</b><br><small>suggested agent: ${escapeHtml(r.drug_name)}</small></span><span>${escapeHtml(r.dose)} ${escapeHtml(r.route)} ${escapeHtml(r.frequency)}</span></div>`).join('')}<p style="margin-top:8px">${escapeHtml(narrow[0].renal_adjustment_note||'')}</p></div>`
        : `<div class="rs-section"><h4>Current regimen remains covered</h4><p>Susceptibility results support the current regimen — no narrower option identified.</p></div>`;
      body += `<div class="rs-section"><p>Reassessment window: <b>${d.reassessment_window_hours}h</b></p></div>`;
    }
    resultEl.innerHTML = govLine + body + `<details style="margin-top:10px"><summary>View raw JSON (audit / developer)</summary><pre>${escapeHtml(JSON.stringify(data,null,2))}</pre></details>`;
    loadAudit();
  }catch(ex){
    err.textContent=ex.message; err.classList.remove('hidden');
  }finally{
    btn.disabled=false; btn.querySelector('span').textContent='Evaluate de-escalation';
  }
});

async function loadAudit(){
  const el=$('#auditFeed');
  try{
    const d=await api('/audit?limit=25');
    const events=d.events||[];
    el.innerHTML = events.length ? events.map(ev=>{
      const status=(ev.status||'—').toUpperCase();
      const cls=(ev.status||'').toLowerCase();
      return `<div class="audit-row"><span class="mono">${escapeHtml(ev.timestamp||'')}</span><span>${escapeHtml(ev.event_type||'')}</span><span>${escapeHtml(ev.case_id||'—')}</span><span class="status-pill ${cls}">${escapeHtml(status)}</span></div>`;
    }).join('') : 'No events yet — run an assessment or de-escalation to see governance decisions here.';
  }catch(e){
    el.textContent='Audit trail unavailable: '+e.message;
  }
}
$('#refreshAudit').addEventListener('click',loadAudit);

function updateGuidelinesBadge(status){
  const badge=$('#guidelinesBadge');
  const count=status.overdue_count || status.pending_count || 0;
  if(count>0){badge.textContent=String(status.pending_count); badge.classList.remove('hidden')}
  else{badge.classList.add('hidden')}
}

async function loadGuidelines(){
  const listEl=$('#guidelinesList'); const banner=$('#guidelinesOverdueBanner');
  try{
    const status=await api('/guidelines/status');
    updateGuidelinesBadge(status);
    $('#gActiveVersion').textContent=status.active_version||'—';
    $('#gPendingCount').textContent=status.pending_count;
    $('#gOverdueCount').textContent=status.overdue_count;
    $('#gVersionCount').textContent=(status.versions||[]).length;
    if(status.overdue_count>0){banner.textContent=`⚠ ${status.overdue_count} guideline review(s) past the ${5}-day SLA — physician/pharmacist decision needed.`;banner.classList.remove('hidden')}
    else{banner.classList.add('hidden')}
    const pending=status.pending||[];
    listEl.innerHTML = pending.length ? pending.map(r=>`
      <div class="review-card ${r.overdue?'overdue':''}">
        <div class="review-head"><span class="review-topic">${escapeHtml(r.topic||'')}</span>${r.overdue?'<span class="pill-overdue">OVERDUE</span>':''}</div>
        <div class="review-meta mono">source: ${escapeHtml(r.source_id||'—')} · confidence: ${r.confidence ?? '—'} · SLA: ${escapeHtml(r.sla_deadline||'—')}</div>
        <div class="review-summary">${escapeHtml(r.summary||'')}</div>
        <div class="review-actions">
          <input type="text" placeholder="Your name" class="reviewer-name" style="width:140px" />
          <button class="ghost approve-btn" data-review="${escapeHtml(r.review_id)}">Approve…</button>
          <button class="ghost reject-btn" data-review="${escapeHtml(r.review_id)}">Reject</button>
        </div>
        <div class="approve-body hidden" data-review="${escapeHtml(r.review_id)}"></div>
      </div>
    `).join('') : '<div>No pending guideline reviews.</div>';
    wireReviewActions();
  }catch(e){
    listEl.textContent='Guidelines unavailable: '+e.message;
  }
}

function wireReviewActions(){
  $$('.approve-btn').forEach(btn=>btn.addEventListener('click', async ()=>{
    const reviewId=btn.dataset.review;
    const body=document.querySelector(`.approve-body[data-review="${reviewId}"]`);
    if(!body.classList.contains('hidden')){body.classList.add('hidden');return}
    body.classList.remove('hidden');
    body.innerHTML='Loading active KB…';
    try{
      const kb=await api('/guidelines/active-kb');
      body.innerHTML=`<textarea rows="8">${escapeHtml(JSON.stringify(kb,null,2))}</textarea><div class="review-actions" style="margin-top:8px"><button class="primary confirm-approve" data-review="${reviewId}"><span>Confirm approve</span></button></div>`;
      body.querySelector('.confirm-approve').addEventListener('click', async ()=>{
        const name=btn.closest('.review-card').querySelector('.reviewer-name').value.trim();
        if(!name){alert('Enter reviewer name first.');return}
        try{
          const content=JSON.parse(body.querySelector('textarea').value);
          await api(`/guidelines/${reviewId}/approve`,{method:'POST',body:JSON.stringify({reviewed_by:name,updated_kb_content:content})});
          loadGuidelines();
        }catch(ex){alert('Approve failed: '+ex.message)}
      });
    }catch(ex){body.innerHTML='Failed to load active KB: '+ex.message}
  }));
  $$('.reject-btn').forEach(btn=>btn.addEventListener('click', async ()=>{
    const reviewId=btn.dataset.review;
    const name=btn.closest('.review-card').querySelector('.reviewer-name').value.trim();
    const reason=prompt('Reason for rejecting this guideline change?');
    if(!name){alert('Enter reviewer name first.');return}
    if(reason===null || reason.trim()==='') return;
    try{
      await api(`/guidelines/${reviewId}/reject`,{method:'POST',body:JSON.stringify({reviewed_by:name,reason:reason.trim()})});
      loadGuidelines();
    }catch(ex){alert('Reject failed: '+ex.message)}
  }));
}

$('#checkGuidelines').addEventListener('click', async ()=>{
  const b=$('#checkGuidelines'); b.disabled=true; b.textContent='Checking…';
  try{ await api('/guidelines/check',{method:'POST'}); await loadGuidelines(); }
  catch(e){ alert('Check failed: '+e.message); }
  finally{ b.disabled=false; b.textContent='Check for updates'; }
});

// Surface the alert badge on load, regardless of which tab is active.
// (Only fires once actually authenticated — see showApp().)
