const API = window.SEPSIS_API_BASE || '';
const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];

function showView(name){
  $$('.view').forEach(v=>v.classList.toggle('active',v.id===name));
  $$('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.view===name));
  const titles={assessment:'Clinical Assessment',governance:'Governance',memory:'Memory & Analytics',architecture:'Five-Agent System'};
  $('#pageTitle').textContent=titles[name]||'Clinical Assessment';
  if(name==='memory') loadAnalytics();
}
$$('.nav-item').forEach(b=>b.addEventListener('click',()=>showView(b.dataset.view)));

async function api(path, options={}){
  const res=await fetch(API+path,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
  const text=await res.text(); let data={}; try{data=JSON.parse(text)}catch{data={detail:text}};
  if(!res.ok) throw new Error(data.detail||`HTTP ${res.status}`);
  return data;
}

function optionalNumber(form,name){const v=form.elements[name].value; return v===''?null:Number(v)}
function checked(form,name){return [...form.querySelectorAll(`input[name="${name}"]:checked`)].map(x=>x.value)}

$('#assessmentForm').addEventListener('submit',async e=>{
  e.preventDefault();
  const form=e.currentTarget; const btn=$('.primary',form); const err=$('#assessmentError');
  err.classList.add('hidden'); btn.disabled=true; btn.querySelector('span').textContent='Running governed assessment…';
  const payload={case_id:form.elements.case_id.value.trim(),patient_id:form.elements.patient_id.value.trim(),severity:form.elements.severity.value,suspected_source:form.elements.suspected_source.value,
    pao2_fio2:optionalNumber(form,'pao2_fio2'),platelets:optionalNumber(form,'platelets'),bilirubin:optionalNumber(form,'bilirubin'),map_mmhg:optionalNumber(form,'map_mmhg'),gcs:optionalNumber(form,'gcs'),creatinine:optionalNumber(form,'creatinine'),urine_output_24h:optionalNumber(form,'urine_output_24h'),weight_kg:optionalNumber(form,'weight_kg'),
    pressor_drug:'none',pressor_dose:null,mdr_risk_factors:checked(form,'mdr'),mrsa_risk_factors:checked(form,'mrsa'),anaerobic_risk_factors:checked(form,'anaerobic'),fungal_risk_factors:checked(form,'fungal'),documented_allergies:form.elements.allergies.value.split(';').map(x=>x.trim()).filter(Boolean)};
  try{const data=await api('/assess',{method:'POST',body:JSON.stringify(payload)}); renderResult(data); document.querySelector('[data-view="assessment"]').click();}
  catch(ex){err.textContent=ex.message;err.classList.remove('hidden')}
  finally{btn.disabled=false;btn.querySelector('span').textContent='Run governed assessment'}
});

function renderResult(data){
  $('#resultPanel').classList.remove('hidden');
  const sofa=data.sofa||{}; $('#sofaScore').textContent=sofa.total ?? sofa.score ?? '—';
  const g=data.governance; const pill=$('#resultStatus'); pill.className='status-pill '+(g?.status?.toLowerCase()||''); pill.textContent=g?.status||data.antibiotic_error||'NO DECISION';
  const ab=$('#antibioticResult'); const a=data.antibiotic;
  if(a){const regimen=a.recommended_regimen||[];ab.innerHTML=`<div><b>Timing target:</b> ${a.timing_target_hours??'—'} h</div>${regimen.map(r=>`<div class="drug"><span>${escapeHtml(r.drug_name||'—')}</span><span>${escapeHtml(r.dose||'')} ${escapeHtml(r.route||'')} ${escapeHtml(r.frequency||'')}</span></div>`).join('')||'<div>No regimen returned.</div>'}`}
  else ab.innerHTML=`<div class="alert error">${escapeHtml(data.antibiotic_error||'No trusted antibiotic output')}</div>`;
  $('#governanceResult').innerHTML=g?`<div><b>Status:</b> ${escapeHtml(g.status)}</div><div><b>KB:</b> ${escapeHtml(g.kb_version||'—')}</div><div><b>Warnings:</b> ${g.warnings?.length?escapeHtml(g.warnings.join('; ')):'None'}</div><div><b>Violations:</b> ${g.violations?.length?escapeHtml(g.violations.join('; ')):'None'}</div>`:'No governance result.';
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
