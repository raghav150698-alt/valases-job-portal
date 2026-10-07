'use strict';
const $ = id => document.getElementById(id);
let state = { jobs: [], user: null, saved: new Set(), view: 'explore', register: false, selectedJob: null, config: null, resetToken: null, paginated: false, total: 0, matchLoaded: 0, searchSequence: 0, searchParams: null };
async function api(path, method = 'GET', body) {
  const options = { method, credentials: 'same-origin', headers: {} };
  if (body instanceof FormData) options.body = body;
  else if (body !== undefined) { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
  const response = await fetch('/api' + path, options);
  const result = await response.json();
  if (!response.ok) {
    const message = typeof result.detail === 'string' ? result.detail : 'Please check the information you entered.';
    const error = new Error(message); error.status = response.status; throw error;
  }
  return result;
}
function configurePublicPreview() {
  document.body.classList.add('public-preview');
  for (const id of ['account-button','save-profile','open-plan','resume-file','auth-submit','checkout-submit']) {
    $(id).disabled = true;
    $(id).title = 'Disabled in the public preview';
  }
  document.querySelector('[data-view="saved"]').disabled = true;
  document.querySelector('.portal-heading p').textContent = 'Explore sample jobs and try matching with fictional experience.';
  document.querySelector('.filter-note p').textContent = 'Try matching with the sample experience text.';
  document.querySelector('.sidebar-foot').textContent = 'Public preview · sample vacancies';
  $('resume').value = 'Sample experience: Built Python APIs, wrote SQL queries, used Git and automated testing with Selenium.';
}
function message(text, error = false) { $('status').textContent = text; $('status').hidden = !text; $('status').className = error ? 'error' : ''; }
function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text) node.textContent = text; return node; }
function empty(container, title, text) { container.replaceChildren(); const box = el('div','empty'); box.append(el('h3','',title),el('p','',text)); container.append(box); }
function profile() { return { resume_text: $('resume').value, preferences: { location: $('preferred-location').value, work_arrangement: $('arrangement').value, experience_years: $('years').value === '' ? null : Number($('years').value) } }; }
function applyProfile(data) { $('resume').value = data.resume_text || ''; const prefs = data.preferences || {}; $('preferred-location').value = prefs.location || ''; $('arrangement').value = prefs.work_arrangement || 'any'; $('years').value = prefs.experience_years ?? ''; }
async function refreshUser() {
  try { state.user = await api('/me'); state.saved = new Set(state.user.saved_jobs); $('account-button').textContent = state.user.name; $('account-email').textContent = state.user.email; applyProfile(state.user.profile);
    $('verification-status').textContent = state.user.email_verified ? 'Email verified' : 'Verify your email to purchase access and receive alerts.';
    $('verify-email').hidden = state.user.email_verified;
    $('alerts-enabled').checked = state.user.profile.alerts_enabled;
    const planText = state.user.plan_active ? 'Access active until ' + new Date(state.user.paid_until).toLocaleDateString() : 'Free account · search and applications included';
    $('account-plan').textContent = $('plan-status').textContent = planText;
    $('open-plan').textContent = state.user.plan_active ? 'Extend access · ₹79' : 'Get 30-day access · ₹79'; }
  catch (error) { if (error.status !== 401) throw error; state.user = null; state.saved = new Set(); $('account-button').textContent = state.config?.public_preview ? 'Preview mode' : 'Sign in / Join'; $('plan-status').textContent='Sign in to save your profile and manage access.'; $('open-plan').textContent='Get 30-day access · '+String.fromCharCode(8377)+'79'; $('more-matches').hidden=true; }
}
function show(view) {
  state.view = view;
  $('intro').hidden = view !== 'explore';
  document.querySelector('.workspace').classList.toggle('focused', view !== 'explore');
  for (const name of ['explore','matches','saved']) $(name + '-view').hidden = name !== view;
  document.querySelectorAll('[data-view]').forEach(button => button.classList.toggle('active', button.dataset.view === view));
  message(''); if (view === 'saved') renderSaved();
}
function metadata(job) {
  const node = el('div','job-meta');
  const arrangements = {remote:'Remote',hybrid:'Hybrid',on_site:'On site'};
  const types = {full_time:'Full time',part_time:'Part time',contract:'Contract',internship:'Internship'};
  node.append(el('span','',job.location || 'Location not specified'));
  const arrangement = arrangements[job.work_arrangement] || job.work_arrangement || 'Arrangement unspecified';
  if ((job.location || '').toLowerCase() !== arrangement.toLowerCase()) node.append(el('span','',arrangement));
  node.append(el('span','',types[job.employment_type] || job.employment_type || 'Type unspecified'));
  return node;
}
async function toggleSaved(job, button) {
  if (!state.user) { $('auth-dialog').showModal(); return; }
  button.disabled = true;
  try {
    const saved = state.saved.has(job.id);
    await api('/me/saved/' + encodeURIComponent(job.id), saved ? 'DELETE' : 'PUT');
    if (saved) state.saved.delete(job.id); else state.saved.add(job.id);
    renderSearch(); if (state.view === 'saved') renderSaved();
  } catch(error) { message(error.message,true); }
  finally { button.disabled = false; }
}
function selectJob(job, scroll = false) {
  state.selectedJob = job.id;
  document.querySelectorAll('.job-row').forEach(row => row.classList.toggle('selected', row.dataset.jobId === job.id));
  document.querySelectorAll('.role-button').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.jobId === job.id)));
  renderDetail(job);
  if (scroll && window.matchMedia('(max-width:620px)').matches) $('job-detail').scrollIntoView({behavior:'smooth',block:'start'});
}
function compactRow(job) {
  const row = el('article','job-row'); row.dataset.jobId = job.id;
  if (state.selectedJob === job.id) row.classList.add('selected');
  const company = el('div','row-company'); company.append(el('span','company-mark',job.company.slice(0,1).toUpperCase()),el('span','',job.company));
  const save = el('button','row-save',state.saved.has(job.id) ? '♥' : '♡'); save.type = 'button'; save.setAttribute('aria-label',(state.saved.has(job.id) ? 'Unsave ' : 'Save ') + job.title); save.onclick = () => toggleSaved(job,save);
  const role = el('button','role-button',job.title); role.type = 'button'; role.dataset.jobId = job.id; role.setAttribute('aria-pressed',String(state.selectedJob === job.id)); role.onclick = () => selectJob(job,true);
  const skills = el('div','skills'); (job.skills || []).slice(0,4).forEach(skill => skills.append(el('span','skill',skill)));
  const bottom = el('div','row-bottom'); bottom.append(el('span','',job.demo ? 'Sample vacancy' : 'Published on Valases')); const open = el('button','row-open','View role →'); open.type = 'button'; open.setAttribute('aria-label','View details for ' + job.title); open.onclick = () => selectJob(job,true); bottom.append(open);
  row.append(company,save,role,metadata(job),skills,bottom); return row;
}
function detailSection(title, text, values) {
  const section = el('div','detail-section'); section.append(el('h4','',title));
  if (text) section.append(el('p','',text));
  if (values && values.length) { const list = el('ul'); values.forEach(value => list.append(el('li','',value))); section.append(list); }
  return section;
}
function renderDetail(job) {
  const detail = $('job-detail'); detail.replaceChildren(); detail.hidden = false;
  const top = el('div','detail-topline'); top.append(el('span','detail-kicker','ROLE OVERVIEW')); const save = el('button','detail-save',state.saved.has(job.id) ? '♥ Saved' : '♡ Save role'); save.type = 'button'; save.onclick = () => toggleSaved(job,save); top.append(save);
  detail.append(top,el('div','detail-company',job.company),el('h3','detail-title',job.title),metadata(job));
  const actions = el('div','detail-actions');
  if (job.apply_url && !job.demo) { const link = el('a','primary','Apply on Valases ↗'); link.href = job.apply_url; link.target = '_blank'; link.rel = 'noopener noreferrer'; actions.append(link,el('span','','Free to apply')); }
  else actions.append(el('span','demo-apply',job.demo ? 'Sample vacancy · applications disabled' : 'Application link unavailable'));
  detail.append(actions,detailSection('The role',job.description || 'The employer has not added a description.'));
  if (job.responsibilities?.length) detail.append(detailSection('What you’ll do',null,job.responsibilities));
  if (job.requirements?.length) detail.append(detailSection('What the employer is looking for',null,job.requirements));
  const skillSection = detailSection('Skills for this role'); const skillList = el('div','detail-skills'); (job.skills || []).forEach(skill => skillList.append(el('span','detail-skill',skill))); if (!job.skills?.length) skillList.append(el('p','','Skills not specified')); skillSection.append(skillList); detail.append(skillSection);
  if (job.minimum_experience_years != null) detail.append(detailSection('Experience', 'At least ' + job.minimum_experience_years + ' years requested by the employer.'));
  const help = el('div','detail-match-entry'); help.append(el('p','','Where does your experience fit?')); const button = el('button','text-button','Find my matching roles →'); button.type='button'; button.onclick=()=>{ show('matches'); $('resume').focus(); }; help.append(button); detail.append(help);
  detail.append(el('p','detail-footnote',job.demo ? 'This is a synthetic role for exploring the product. It is not a live hiring opportunity.' : 'The receiving employer reviews your application. A match does not guarantee an interview.'));
}
function card(job, match) {
  const node = el('article','job-card'); const top = el('div','job-top'); const title = el('div');
  title.append(el('div','company',job.company),el('h3','',job.title));
  const meta = el('div','job-meta'); meta.append(el('span','',job.location || 'Location not specified'),el('span','',(job.work_arrangement || '').replaceAll('_',' ')),el('span','',(job.employment_type || '').replaceAll('_',' '))); title.append(meta); top.append(title);
  const save = el('button','save',state.saved.has(job.id) ? '♥' : '♡'); save.type = 'button'; save.setAttribute('aria-label',state.saved.has(job.id) ? 'Unsave ' + job.title : 'Save ' + job.title);
  save.onclick = async () => { if (!state.user) { $('auth-dialog').showModal(); return; } save.disabled = true; try { const saved = state.saved.has(job.id); await api('/me/saved/' + encodeURIComponent(job.id), saved ? 'DELETE' : 'PUT'); if (saved) state.saved.delete(job.id); else state.saved.add(job.id); save.textContent = saved ? '♡' : '♥'; save.setAttribute('aria-label', saved ? 'Save ' + job.title : 'Unsave ' + job.title); if (state.view === 'saved') renderSaved(); } catch(error) { message(error.message,true); } finally { save.disabled = false; } }; top.append(save); node.append(top);
  node.append(el('p','job-description',(job.description || '').slice(0,320)));
  const skills = el('div','skills'); (job.skills || []).forEach(skill => skills.append(el('span','skill',skill))); node.append(skills);
  if (match) { const fit = el('div','match-evidence'); fit.append(el('span','pill',match.band)); fit.append(el('p','', 'Résumé mentions: ' + match.matched_skills.join(', '))); if (match.missing_skills.length) fit.append(el('p','','Not confirmed: ' + match.missing_skills.join(', '))); match.notes.forEach(note => fit.append(el('p','',note))); const details = el('details'); details.append(el('summary','','See supporting résumé text')); Object.entries(match.evidence).forEach(([skill,quote]) => details.append(el('p','',skill + ': “' + quote + '”'))); fit.append(details); node.append(fit);
    if (state.user?.plan_active) { const hide = el('button','text-button','Not interested in this role'); hide.type='button'; hide.onclick=async()=>{ try { await api('/me/feedback','POST',{job_id:job.id,reason:'not_interested'}); node.remove(); message('Role hidden from your matches and alerts.'); const undo=el('button','text-button','Undo'); undo.type='button'; undo.onclick=async()=>{try{await api('/me/feedback/'+encodeURIComponent(job.id),'DELETE'); $('matches').append(card(job,match));message('Role restored.');}catch(error){message(error.message,true);}}; $('status').append(undo); } catch(error) { message(error.message,true); } }; node.append(hide); } }
  const foot = el('div','card-footer'); foot.append(el('small','',job.demo ? 'Sample vacancy · applications disabled' : 'Application opens on Valases'));
  if (job.apply_url && !job.demo) { const link = el('a','outline','View & apply ↗'); link.href = job.apply_url; link.target = '_blank'; link.rel = 'noopener noreferrer'; foot.append(link); } else foot.append(el('span','pill',job.demo ? 'Demo' : 'Application link unavailable')); node.append(foot); return node;
}
async function renderSaved() { let jobs; try { jobs = state.user ? (await api('/me/saved')).items : []; } catch(error) { message(error.message,true); return; } if (!state.user) empty($('saved'),'Keep your shortlist in one place','Sign in to save opportunities to your private account.'); else if (!jobs.length) empty($('saved'),'Your shortlist starts here','Save a job using the heart icon. Closed jobs disappear from this list.'); else $('saved').replaceChildren(...jobs.map(job => card(job))); }
async function loadJobs(more=false) { const sequence=++state.searchSequence; try {
  let params=new URLSearchParams({q:$('query').value,location:$('search-location').value,offset:String(more?state.jobs.length:0),limit:'50',arrangement:Array.from(document.querySelectorAll('.work-filter:checked')).map(input=>input.value).join(','),employment_type:Array.from(document.querySelectorAll('.type-filter:checked')).map(input=>input.value).join(',')});
  if(more && state.searchParams) params=new URLSearchParams(state.searchParams); params.set('offset',String(more?state.jobs.length:0)); state.searchParams=params.toString();
  const result=await api('/jobs?'+params); if(sequence!==state.searchSequence)return; state.jobs=more?[...state.jobs,...result.items]:result.items;state.paginated=!!result.paginated;state.total=result.total||result.items.length;renderSearch();$('load-more').hidden=!state.paginated||state.jobs.length>=state.total;if(state.view==='saved')renderSaved();
} catch(error) { message(error.message,true);empty($('jobs'),'Jobs temporarily unavailable','Please retry shortly.'); } }
function updateSearch(){ if(state.paginated)loadJobs();else renderSearch(); }
$('load-more').onclick=()=>loadJobs(true);

function renderSearch() {
  const query = $('query').value.trim().toLowerCase(), location = $('search-location').value.trim().toLowerCase();
  const arrangements = new Set(Array.from(document.querySelectorAll('.work-filter:checked')).map(input => input.value));
  const types = new Set(Array.from(document.querySelectorAll('.type-filter:checked')).map(input => input.value));
  const textMatches = state.paginated ? state.jobs : state.jobs.filter(job => (job.title + ' ' + job.company + ' ' + (job.skills || []).join(' ')).toLowerCase().includes(query) && (job.location || '').toLowerCase().includes(location));
  for (const type of ['remote','hybrid','on_site']) $('count-' + type).textContent = state.paginated ? '' : textMatches.filter(job => job.work_arrangement === type).length;
  const jobs = textMatches.filter(job => (!arrangements.size || arrangements.has(job.work_arrangement)) && (!types.size || types.has(job.employment_type)));
  $('job-count').textContent = state.paginated ? state.total : jobs.length;
  $('results-context').textContent = query || location || arrangements.size || types.size ? (state.paginated ? state.total : jobs.length) + ' jobs match your search' : 'All jobs';
  if (!jobs.length) { empty($('jobs'),'No roles match this search','Try another skill, city or work arrangement.'); $('job-detail').hidden = true; state.selectedJob = null; }
  else {
    const selected = jobs.find(job => job.id === state.selectedJob) || jobs[0]; state.selectedJob = selected.id;
    $('jobs').replaceChildren(...jobs.map(compactRow)); renderDetail(selected);
  }
}
document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => show(button.dataset.view));
$('hero-match').onclick = $('premium-preview').onclick = () => { show('matches'); $('matches-view').scrollIntoView({behavior:'smooth'}); };
$('search').onsubmit = event => { event.preventDefault(); updateSearch(); };
document.querySelectorAll('.work-filter').forEach(input => input.onchange = updateSearch);
document.querySelectorAll('.type-filter').forEach(input => input.onchange = updateSearch);
$('clear-filters').onclick = () => { document.querySelectorAll('.work-filter,.type-filter').forEach(input => input.checked = false); $('query').value = ''; $('search-location').value = ''; updateSearch(); };
document.querySelectorAll('[data-search],[data-location]').forEach(button => button.onclick = () => {
  document.querySelectorAll('.work-filter,.type-filter').forEach(input => input.checked = false);
  $('query').value = button.dataset.search || ''; $('search-location').value = button.dataset.location || '';
  updateSearch();
});
$('profile-form').onsubmit = async event => { event.preventDefault(); const button = event.submitter; button.disabled = true; message('Finding jobs with relevant skill evidence…'); try { let result; if (state.user?.plan_active) { await api('/me/profile','PUT',profile()); result = await api('/me/matches'); } else result = await api('/matches/preview','POST',profile()); $('match-summary').textContent = result.preview ? result.total + ' potential matches · showing up to 3 in the free preview' : result.total + ' matching roles'; if (!result.items.length) empty($('matches'),'No convincing matches found yet','Try adjusting your preferences, review your résumé text, or return when more jobs are available.'); else $('matches').replaceChildren(...result.items.map(match => card(match.job,match))); state.matchLoaded=result.items.length; $('more-matches').hidden=result.preview||state.matchLoaded>=result.total; message('Matches ready. Review the requirements before applying.'); } catch(error) { message(error.message,true); } finally { button.disabled = false; } };
$('save-profile').onclick = async () => { if (!state.user) { $('auth-dialog').showModal(); return; } try { await api('/me/profile','PUT',profile()); message('Profile saved to your private Jobs account.'); } catch(error) { message(error.message,true); } };
$('resume-file').onchange = async () => { const file = $('resume-file').files[0]; if (!file) return; if (file.size > 2 * 1024 * 1024) { message('Please use a file under 2 MB.',true); return; } const data = new FormData(); data.append('file',file); message('Reading your résumé…'); try { const result = await api('/resume/extract','POST',data); $('resume').value = result.resume_text; message(result.message); } catch(error) { message(error.message,true); } $('resume-file').value = ''; };
$('account-button').onclick = () => $(state.user ? 'account-dialog' : 'auth-dialog').showModal();
$('close-auth').onclick = () => $('auth-dialog').close(); $('close-account').onclick = () => $('account-dialog').close();
$('toggle-auth').onclick = () => { state.register = !state.register; $('name-field').hidden = !state.register; $('name').required = state.register; $('terms-field').hidden=!state.register; $('accept-terms').required=state.register; $('auth-title').textContent = $('auth-submit').textContent = state.register ? 'Create account' : 'Sign in'; $('toggle-auth').textContent = state.register ? 'Already have an account? Sign in' : 'New here? Create an account'; $('password').autocomplete = state.register ? 'new-password' : 'current-password'; $('auth-error').textContent = ''; };
$('auth-form').onsubmit = async event => { event.preventDefault(); $('auth-submit').disabled = true; try { const currentProfile = profile(); await api('/auth/' + (state.register ? 'register' : 'login'),'POST',{email:$('email').value,password:$('password').value,name:$('name').value || 'Candidate',accepted_terms:$('accept-terms').checked}); await refreshUser(); if (!state.user.profile.resume_text && currentProfile.resume_text) applyProfile(currentProfile); $('auth-dialog').close(); $('password').value = ''; message('Signed in. You can now save your profile and jobs.'); await loadJobs(); } catch(error) { $('auth-error').textContent = error.message; } finally { $('auth-submit').disabled = false; } };
$('logout').onclick = async () => { try { await api('/auth/logout','POST'); await refreshUser(); $('account-dialog').close(); applyProfile({}); $('matches').replaceChildren(); show('explore'); await loadJobs(); } catch(error) { message(error.message,true); } };
$('delete-account').onclick = async () => { if (!window.confirm('Delete your Valases Jobs account, résumé profile and saved jobs? Employer-held applications are separate.')) return; try { await api('/me','DELETE'); await refreshUser(); $('account-dialog').close(); applyProfile({}); $('matches').replaceChildren(); show('explore'); await loadJobs(); message('Your Jobs account and profile have been deleted.'); } catch(error) { message(error.message,true); } };


function showLinkNotice(container, result, fallback) {
  container.textContent = fallback;
  if (result.demo_link) { const link=el('a','text-button','Open local test link'); link.href=result.demo_link; link.onclick=()=>{ document.querySelectorAll('dialog[open]').forEach(d=>d.close()); setTimeout(handleLinks,0); }; container.append(el('p','','Email delivery is disabled locally.'),link); }
}
$('verify-email').onclick=async()=>{ try { const result=await api('/auth/verification','POST'); showLinkNotice($('account-notice'),result,'Verification email queued. Check your inbox.'); } catch(error) { $('account-notice').textContent=error.message; } };
$('alerts-enabled').onchange=async()=>{ const enabled=$('alerts-enabled').checked; try { await api('/me/alerts','PUT',{enabled}); $('account-notice').textContent=enabled ? 'Daily alerts enabled. We email only new matching roles.' : 'Email alerts disabled.'; } catch(error) { $('alerts-enabled').checked=!enabled; $('account-notice').textContent=error.message; } };
$('open-plan').onclick=()=>{ if (!state.user) { $('auth-dialog').showModal(); return; } $('checkout-status').textContent=state.config?.checkout_enabled ? '' : 'Payments will open when the live payment service is connected.'; $('checkout-submit').disabled=!state.config?.checkout_enabled; $('plan-dialog').showModal(); };
$('close-plan').onclick=()=>$('plan-dialog').close();
$('checkout-form').onsubmit=async event=>{ event.preventDefault(); $('checkout-submit').disabled=true; try {
  let key=sessionStorage.getItem('jobs_checkout_key'); if(!key){key=crypto.randomUUID();sessionStorage.setItem('jobs_checkout_key',key);}
  const order=await api('/billing/orders','POST',{phone:$('payment-phone').value,idempotency_key:key});
  sessionStorage.setItem('jobs_order_id',order.order_id);
  if (!window.Cashfree) await new Promise((resolve,reject)=>{const script=document.createElement('script'); script.src='https://sdk.cashfree.com/js/v3/cashfree.js';script.onload=resolve;script.onerror=()=>reject(new Error('Payment checkout could not load'));document.head.append(script);});
  await window.Cashfree({mode:order.mode}).checkout({paymentSessionId:order.payment_session_id,redirectTarget:'_self'});
} catch(error) { $('checkout-status').textContent=error.message; } finally { $('checkout-submit').disabled=false; } };
$('forgot-password').onclick=()=>{ $('auth-dialog').close(); state.resetToken=null; $('recovery-email-label').hidden=false; $('recovery-password-label').hidden=true; $('recovery-email').required=true; $('recovery-password').required=false; $('recovery-status').textContent=''; $('recovery-dialog').showModal(); };
$('close-recovery').onclick=()=>$('recovery-dialog').close();
$('recovery-form').onsubmit=async event=>{ event.preventDefault(); const button=event.submitter;button.disabled=true;try {
 if(state.resetToken){await api('/auth/reset-password','POST',{token:state.resetToken,password:$('recovery-password').value});state.resetToken=null;$('recovery-password').value='';$('recovery-dialog').close();await refreshUser();message('Password reset. Sign in with your new password.');}
 else {const result=await api('/auth/forgot-password','POST',{email:$('recovery-email').value});showLinkNotice($('recovery-status'),result,result.message);}
} catch(error) { $('recovery-status').textContent=error.message; } finally {button.disabled=false;} };
async function handleLinks(){
 const params=new URLSearchParams(location.hash.slice(1)); const verify=params.get('verify_token'),reset=params.get('reset_token'),unsubscribe=params.get('unsubscribe_token');
 if(verify||reset||unsubscribe)history.replaceState(null,'',location.pathname+location.search);
 try { if(verify){await api('/auth/verify','POST',{token:verify});await refreshUser();message('Email verified.');}
 if(unsubscribe){await api('/alerts/unsubscribe','POST',{token:unsubscribe});await refreshUser();message('Job email alerts disabled.');}
 if(reset){state.resetToken=reset;$('recovery-email-label').hidden=true;$('recovery-password-label').hidden=false;$('recovery-email').required=false;$('recovery-password').required=true;$('recovery-status').textContent='Choose a new password with at least 12 characters.';$('recovery-dialog').showModal();}
 }catch(error){message(error.message,true);}
}
window.addEventListener('hashchange',handleLinks);
(async()=>{ try {state.config=await api('/config');if(state.config.public_preview)configurePublicPreview();await refreshUser();await loadJobs();if(!state.config.public_preview)await handleLinks();const orderId=new URLSearchParams(location.search).get('order_id');if(orderId&&state.user){const result=await api('/billing/orders/'+encodeURIComponent(orderId)+'/verify','POST');await refreshUser();if(result.granted){sessionStorage.removeItem('jobs_checkout_key');sessionStorage.removeItem('jobs_order_id');message('Payment verified. Your 30-day access is active.');}else message('Payment is pending. Check your account again shortly.');history.replaceState(null,'','/');}}catch(error){message(error.message,true);}})();

$('more-matches').onclick=async()=>{ const button=$('more-matches');button.disabled=true;try {const result=await api('/me/matches?offset='+state.matchLoaded+'&limit=50');result.items.forEach(match=>$('matches').append(card(match.job,match)));state.matchLoaded+=result.items.length;button.hidden=state.matchLoaded>=result.total;}catch(error){message(error.message,true);}finally{button.disabled=false;}};
