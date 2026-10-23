import {App} from '@modelcontextprotocol/ext-apps';
const app=new App({name:'Jobwatch',version:'2.0.0'},{}),$=id=>document.getElementById(id);
let runId,rendered,busy=false,cardKind='auto',subjectId='0',currentApplication=null,frameBusy=false;
let modelDraft={},modelSettingsOpen=false,modelSaving=false,modelNotice='';
const previews=new Map(),drafts=new Map(),files=new Map(),selectedJobs=new Map(),controlGrants=new Map(),operationKeys=new Map();
let inputQueue=Promise.resolve();
const short=value=>String(value??'').replaceAll('_',' ');
function node(tag,text,parent,cls){const n=document.createElement(tag);n.textContent=text??'';if(cls)n.className=cls;parent.append(n);return n;}
function section(title,parent=$('body')){const s=node('section','',parent);node('h2',title,s);return s;}
const privateKeys=new Set(['binding','digest','run_key','proposal_digest','scope_digest','person','path','config_hash','input_hash','request_key','expected_run_keys','expected_entry_ids','subject_id']);
function readable(value,parent){
 if(value==null)return;
 if(Array.isArray(value)){for(const item of value){const row=node('div','',parent,'card');readable(item,row);}return;}
 if(typeof value==='object'){const list=node('dl','',parent);for(const [key,v] of Object.entries(value)){if(privateKeys.has(key)||key.endsWith('_hash')||key.endsWith('_id')||v==null)continue;node('dt',short(key),list);readable(v,node('dd','',list));}return;}
 node('p',typeof value==='boolean'?(value?'Yes':'No'):String(value),parent);
}
function details(title,value,parent){const d=node('details','',parent);node('summary',title,d);if(typeof value==='string')node('pre',value,d);else readable(value,d);return d;}
function field(label,parent,key,{multiple=false,type='text',options=[]}={}){
 const row=node('label',label,parent),input=node(options.length?'select':multiple?'textarea':'input','',row);
 if(options.length){for(const option of options){const value=typeof option==='object'?String(option.value??option.label):String(option);const item=node('option',typeof option==='object'?option.label??value:value,input);item.value=value;}}
 else if(!multiple)input.type=type;
 input.setAttribute('aria-label',label);input.value=drafts.get(key)??'';input.maxLength=4000;
 input.oninput=()=>drafts.set(key,input.value);input.onchange=input.oninput;return input;
}
function button(text,parent,fn,primary=false){const b=node('button',text,parent,primary?'primary':'');b.type='button';b.onclick=async()=>{b.disabled=true;try{await fn();await refresh(true);}catch(e){$('status').textContent=e.message;}finally{b.disabled=false;}};return b;}
function resultValue(result){if(result.isError)throw new Error('This action could not be completed. Your changes are retained; review the current state and try again.');if(result._meta?.jobwatch)return result._meta.jobwatch;if(result.structuredContent)return result.structuredContent;return JSON.parse(result.content.find(c=>c.type==='text').text);}
async function action(action,arguments_){return resultValue(await app.callServerTool({name:'jobwatch_action',arguments:{action,arguments:arguments_}}));}
async function resource(uri){const res=await app.readServerResource({uri});return JSON.parse(res.contents.find(c=>c.text!==undefined).text);}
async function showCard(kind,subject='0'){cardKind=kind;subjectId=String(subject);rendered=null;currentApplication=null;await refresh(true);}
const operationNames={profile_confirm:'Confirm your profile and search scope',prepare_application:'Prepare application documents',run_career_ops:'Prepare application documents',submit_application:'Submit the reviewed application',revise_application:'Revise your application documents',select_jobs:'Prepare the selected jobs'};
function decisions(run,profile){
 for(const item of run.interactions.filter(i=>!i.answered)){
  const s=section(item.type==='approval'?'Your decision':'A question for you');
  if(item.type==='approval'){
   node('p',operationNames[item.operation]||short(item.operation),s);
   if(item.binding?.subject)details('What you are approving',item.binding.subject,s);
   else if(item.binding?.arguments)details('What you are approving',item.binding.arguments,s);
   let valid=true;
   if(item.operation==='profile_confirm'){const c=profile.confirmation,b=item.binding;valid=!!c&&c.proposal_digest===b.proposal_digest&&c.scope_digest===b.scope_digest;readable({profile:profile.proposal?.facts,search_scope:c?.scope},s);if(!valid)node('p','The draft changed. Ask Jobwatch to show the current confirmation.',s,'notice');}
   if(item.operation==='submit_application'){valid=false;node('p','Review the live employer form and attachments before submitting.',s,'notice');button('Review employer form',s,()=>showCard('application',item.binding?.arguments?.posting_id||item.posting_id));}
   const row=node('div','',s,'row');if(valid)button(item.operation==='submit_application'?'Confirm final Submit':'Confirm',row,()=>action('respond',{id:item.id,decision:'approve'}),true);button('Decline',row,()=>action('respond',{id:item.id,decision:'reject'}));
  }else{const input=field(item.question||'Your answer',s,'interaction:'+item.id,{multiple:true});const row=node('div','',s,'row');button('Send answer',row,()=>action('respond',{id:item.id,decision:'answer',answer:input.value}),true);button('Skip',row,()=>action('respond',{id:item.id,decision:'decline'}));}
 }
}
function profileCard(profile,run){
 const s=section(profile.proposal?'Let’s finish your profile':'Your profile');
 if(profile.proposal){const p=profile.proposal;node('p',p.status==='parsing'?'Reading your documents. You can answer questions while this runs.':'Review the evidence and fill in any gaps.',s);
  for(const q of p.questions||[]){const input=field(q.text,s,'profile:'+p.id+':'+q.id,{multiple:true});if(q.why)node('small',q.why,s);button('Save answer',s,()=>action('profile_answer',{id:p.id,expected_revision:p.revision,question_id:q.id,text:input.value}));}
  details('Your evidence and its sources',p.facts,s);
  if(profile.confirmation&&!run.interactions.some(i=>!i.answered&&i.operation==='profile_confirm'&&i.binding?.arguments?.proposal_id===p.id)){const c=profile.confirmation;readable(c.scope,s);button('Confirm profile and search scope',s,()=>action('profile_confirm',{id:p.id,proposal_digest:c.proposal_digest,scope_digest:c.scope_digest}),true);}
 }else node('p',profile.current?.version?'Your confirmed profile is ready. You can add supporting evidence here.':'Add your CV and supporting documents. Jobwatch will guide you through confirmation before searching.',s);
 upload(s,profile);
}
function jobsCard(shortlist){
 const s=section('Jobs worth considering');
 if(!shortlist.entries?.length){node('p',shortlist.status==='stale'?'Your matches need updating. Ask Jobwatch to refresh them.':'Your matches will appear here after your confirmed profile has been assessed.',s);return;}
 for(const entry of shortlist.entries){const c=section(entry.posting?.title||'Job match',s);node('p',[entry.posting?.company,entry.posting?.location].filter(Boolean).join(' · '),c,'muted');node('span',short(entry.label),c,'badge');node('p',entry.rank_reason||entry.objective_fit,c);if(entry.uncertainty)node('p',entry.uncertainty,c,'notice');details('Evidence and open questions',{evidence:entry.evidence,requirements:entry.requirements,unresolved:entry.unresolved,conditions:entry.conditions},c);
  const row=node('label','Prepare documents for this job',c),check=node('input','',row);check.type='checkbox';check.checked=selectedJobs.has(entry.posting_id);check.onchange=()=>check.checked?selectedJobs.set(entry.posting_id,entry):selectedJobs.delete(entry.posting_id);
 }
 button('Prepare selected jobs',s,async()=>{const rows=[...selectedJobs.values()].sort((a,b)=>a.posting_id-b.posting_id);if(!rows.length||rows.length>10)throw new Error('Choose between one and ten jobs.');const visible=new Map(shortlist.entries.map(e=>[e.posting_id,e]));if(rows.some(e=>visible.get(e.posting_id)?.entry_id!==e.entry_id))throw new Error('These matches changed. Refresh and choose again.');const fingerprint=JSON.stringify(rows.map(e=>[e.posting_id,e.entry_id,e.run_key]).sort((a,b)=>a[0]-b[0]));if(!operationKeys.has(fingerprint))operationKeys.set(fingerprint,crypto.randomUUID());await action('select_jobs',{request_key:operationKeys.get(fingerprint),posting_ids:rows.map(e=>e.posting_id),expected_entry_ids:Object.fromEntries(rows.map(e=>[e.posting_id,e.entry_id])),expected_run_keys:Object.fromEntries(rows.map(e=>[e.posting_id,e.run_key]))});operationKeys.delete(fingerprint);selectedJobs.clear();await showCard('progress');},true);
}
function progressCard(run,selections){
 if(!run.interactions.some(i=>!i.answered)){const s=section(['queued','running'].includes(run.state)?'Jobwatch is working':'Saved work');node('p',['queued','running'].includes(run.state)?'You can leave and return. Your progress is saved.':short(run.error||run.state),s);}
 for(const selected of selections){const work=section('Application preparation');node('p',short(selected.run?.state||selected.state),work);if(selected.error||selected.run?.error)node('p','This work needs attention. Your saved progress is retained.',work,'notice');documents(selected.run||{},work);if(['pending_dispatch','queued','running'].includes(selected.state))button('Cancel preparation',work,()=>action('cancel_selection',{id:selected.id}));}
 const controls=node('div','',$('body'),'row');if(['queued','running','waiting_for_input','waiting_for_approval','interrupted'].includes(run.state))button('Cancel this work',controls,()=>action('cancel',{id:run.id}));if(['interrupted','deferred'].includes(run.state))button('Retry saved work',controls,()=>action('retry',{id:run.id}));
}
function documents(run,parent){
 if(!run.artifacts?.length)return;
 const s=section('Your documents',parent);
 for(const artifact of run.artifacts){const c=node('div','',s,'card');node('h3',short(artifact.kind),c);const row=node('div','',c,'row');button('Preview',row,async()=>{const doc=await resource('jobwatch://artifacts/'+artifact.id);previews.set(artifact.id,doc.text);});button('Download',row,async()=>{const value=await action('download_ticket',{id:artifact.id});const opened=await app.openLink({url:value.url});if(opened.isError)throw new Error('The download could not be opened.');});if(previews.has(artifact.id))details('Verified document text',previews.get(artifact.id),c).open=true;}
}
function documentsCard(run,selections,applications){
 documents(run,$('body'));for(const selection of selections)if(selection.run)documents(selection.run,$('body'));
 if(!run.artifacts?.length&&!selections.some(s=>s.run?.artifacts?.length))node('p','Prepared documents will appear here when they pass verification.',$('body'));
 const s=section('Request a revision');const target=field('Application to revise',s,'revision-target:'+run.id,{options:(applications||[]).map(a=>({value:String(a.posting_id),label:a.title+' · '+a.company}))});const input=field('What would you like changed?',s,'revision:'+run.id,{multiple:true});button('Ask Jobwatch to revise',s,async()=>{if(!input.value.trim()||!target.value)throw new Error('Choose an application and describe the change first.');await app.sendMessage({role:'user',content:[{type:'text',text:'Please revise my documents for posting '+target.value+': '+input.value}]});});
 applicationChoices(applications,$('body'));
}
function applicationChoices(applications,parent){for(const application of applications||[]){const s=section(application.title||'Application',parent);node('p',application.company,s,'muted');node('p',short(application.submission?.status||application.status||'Documents prepared'),s);button('Review employer application',s,()=>showCard('application',application.posting_id));}}
async function enableControls(pid){const cap=await action('browser_control',{posting_id:pid});controlGrants.set(pid,{...cap,expires:Date.now()+cap.expires_in*1000});}
function browserAction(pid,value,throwOnError=false){
 previews.delete('review:'+pid);
 const operation=inputQueue.then(async()=>{const cap=controlGrants.get(pid);if(!cap||cap.expires<=Date.now())throw new Error('Enable browser controls again to continue editing.');const res=await fetch(cap.url,{method:'POST',headers:{'Content-Type':'text/plain'},body:cap.ticket+'\n'+JSON.stringify(value),credentials:'include',redirect:'error'});if(!res.ok)throw new Error('Browser control paused. Refresh the review; use Confirm final Submit to send the application.');});inputQueue=operation.catch(e=>{controlGrants.delete(pid);$('status').textContent=e.message;});return throwOnError?operation:inputQueue;
}
function applicationCard(application,applications){
 if(!application){applicationChoices(applications,$('body'));if(!applications.length)node('p','Prepare a verified document package before opening an employer application.',$('body'));return;}
 const pid=application.posting_id,s=section(application.title||'Employer application');node('p',application.company,s,'muted');
 const submission=application.submission;
 if(submission){node('p','Submission: '+short(submission.status),s,'notice');if(['pending','pressed','submitted','unsure'].includes(submission.status)){if(submission.status==='unsure')node('p','Jobwatch cannot confirm whether this was received. Check the employer’s page; it will not retry automatically.',s);}}
 if(application.restart_required&&application.can_prepare&&!['pending','pressed','submitted','unsure'].includes(submission?.status)){
  node('p','The previous form session or document package changed. Start a fresh fill, then review the new form before submitting.',s,'notice');
  button('Fill application again',s,()=>action('browser_restart',{posting_id:pid,preparation_run_id:application.previous_preparation_run_id,package_key:application.package_key}),true);
 }
 if(!application.browser?.open){node('p','Open the employer’s application here to fill and review it.',s);if(application.can_prepare&&!application.restart_required)button('Open and fill application',s,()=>action('browser_open',{posting_id:pid}),true);return;}
 node('p',application.browser.automation_active?'Filling the form. Browser controls become available when Jobwatch pauses.':'Review the live employer page. Enable controls to sign in, handle verification or make corrections.',s);
 const img=node('img','',s);img.id='employer-browser';img.alt='Live employer application browser';img.tabIndex=0;img.style.width='100%';img.style.height='auto';img.setAttribute('aria-label','Employer application browser. Shift Escape leaves browser controls.');currentApplication=pid;
 if(!application.browser.automation_active){button('Enable browser controls',s,()=>enableControls(pid));
  const text=field('Text for the focused employer field',s,'browser-text:'+pid,{multiple:true});
  const controls=node('div','',s,'row');button('Enter text in employer form',controls,async()=>{if(!text.value)throw new Error('Enter text first, then choose a field in the employer page.');await browserAction(pid,{kind:'type',text:text.value},true);drafts.delete('browser-text:'+pid);text.value='';});button('Previous field',controls,()=>browserAction(pid,{kind:'key',key:'Shift+Tab'}));button('Next field',controls,()=>browserAction(pid,{kind:'key',key:'Tab'}));
 }
 img.onclick=e=>{const rect=img.getBoundingClientRect();browserAction(pid,{kind:'click',x:(e.clientX-rect.left)*img.naturalWidth/rect.width,y:(e.clientY-rect.top)*img.naturalHeight/rect.height});img.focus();};
 img.onkeydown=e=>{if(e.shiftKey&&e.key==='Escape'){e.preventDefault();$('refresh').focus();return;}if(e.key.length===1&&!e.ctrlKey&&!e.metaKey){e.preventDefault();browserAction(pid,{kind:'type',text:e.key});return;}const key=(e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='a'?(e.metaKey?'Meta+A':'Control+A'):e.shiftKey&&e.key==='Tab'?'Shift+Tab':e.key;if(['Enter','Tab','Shift+Tab','Backspace','Delete','Escape','ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','PageUp','PageDown','Space','Control+A','Meta+A'].includes(key)){e.preventDefault();browserAction(pid,{kind:'key',key});}};
 img.onpaste=e=>{e.preventDefault();browserAction(pid,{kind:'type',text:e.clipboardData.getData('text/plain')});};img.onwheel=e=>{e.preventDefault();browserAction(pid,{kind:'scroll',dx:Math.max(-5000,Math.min(5000,e.deltaX)),dy:Math.max(-5000,Math.min(5000,e.deltaY))});};
 if(application.missing?.length){const answers={};for(const question of application.missing){const key='application:'+application.preparation_run_id+':'+question.question_id;let input;
  if(question.type==='checkbox'||question.kind==='radio'){input=field(question.question,s,key,{type:'checkbox'});input.checked=drafts.get(key)===true;input.onchange=()=>drafts.set(key,input.checked);}
  else{input=field(question.question,s,key,{multiple:!question.options?.length,options:question.options||[]});if(question.multiple||question.type==='select-multiple'){input.multiple=true;const saved=drafts.get(key)||[];for(const option of input.options)option.selected=Array.isArray(saved)&&saved.includes(option.value);input.onchange=()=>drafts.set(key,Array.from(input.selectedOptions).map(o=>o.value));}}
  answers[question.question_id]=input;}
  button('Save answers and continue',s,()=>action('browser_answers',{posting_id:pid,preparation_run_id:application.preparation_run_id,answers:Object.fromEntries(Object.entries(answers).map(([key,input])=>[key,input.type==='checkbox'?input.checked:input.multiple?Array.from(input.selectedOptions).map(o=>o.value):input.value]))}),true);
 }
 const review=previews.get('review:'+pid);
 if(review?.status==='blocked'){node('p',({application_not_ready:'The form is not ready for review yet. Finish the pending questions or browser verification first.',application_changed:'The employer page changed. Fill and review this application again.',final_control_changed:'The employer’s submission control changed. A new review is required.',form_review_changed:'The form changed while it was being read. Read it again.',unsupported_form_review:'This employer uses form controls Jobwatch cannot safely review. Submission remains blocked here.',form_review_unavailable:'Jobwatch cannot read every part of this form safely. Submission remains blocked here.'})[review.reason]||'This form cannot be safely reviewed yet. Submission remains blocked here.',s,'notice');}
 else if(review){node('h3','The form you are reviewing',s);node('p',review.employer+' · '+review.url,s);for(const field of review.fields||[]){node('strong',field.label,s);node('p',field.value,s);}details('Attached documents',review.documents,s);
  if(!review.confirmed_digest)button('Update review after my corrections',s,async()=>{await action('browser_review',{posting_id:pid,digest:review.review_digest});previews.delete('review:'+pid);},true);
  else if(!submission||!['pending','pressed','submitted','unsure'].includes(submission.status)){
   const pending=lastState.run.interactions.find(i=>!i.answered&&i.operation==='submit_application'&&(i.binding?.arguments?.posting_id??i.posting_id)===pid);
   if(pending&&pending.binding?.run_key!==review.confirmed_digest){node('p','The earlier Submit request is for a different form. Decline it before requesting a new confirmation.',s,'notice');button('Decline the outdated Submit request',s,()=>action('respond',{id:pending.id,decision:'reject'}));}
   else button('Confirm final Submit',s,async()=>{if(pending)await action('respond',{id:pending.id,decision:'approve'});else await action('browser_submit',{posting_id:pid,digest:review.confirmed_digest,request_key:crypto.randomUUID()});previews.delete('review:'+pid);},true);
  }
 }
 if(!application.browser.automation_active)button('Read current form and attachments',s,async()=>{previews.set('review:'+pid,await resource('jobwatch://browser/'+pid+'/review'));},true);
 void updateFrame();
}
async function updateFrame(){if(currentApplication==null||frameBusy||!$('employer-browser'))return;frameBusy=true;const pid=currentApplication;try{const image=await resource('jobwatch://browser/'+pid+'/frame');if(currentApplication===pid&&$('employer-browser'))$('employer-browser').src='data:image/jpeg;base64,'+image.jpeg;}catch{$('status').textContent='The browser view is paused. Refresh to reconnect.';}finally{frameBusy=false;}}
let lastState;
function render(data){lastState=data;const {run,profile,selections=[],applications=[],card}=data,root=$('body');root.replaceChildren();currentApplication=null;document.querySelector('h1').textContent=card.title;$('phase').textContent=short(run.state);$('status').textContent=['queued','running'].includes(run.state)?'Jobwatch is working. This card updates automatically.':'Your saved Jobwatch work.';
 decisions(run,profile);
 if(card.kind==='profile')profileCard(profile,run);else if(card.kind==='models')renderModels(data.models,root);else if(card.kind==='jobs')jobsCard(data.shortlist);else if(card.kind==='documents')documentsCard(run,selections,applications);else if(card.kind==='application')applicationCard(data.application,applications);else progressCard(run,selections);
}
function upload(parent,profile){
 const row=node('label','Add your CV or supporting document (PDF, DOCX, TXT or MD; up to 10 MiB)',parent),file=node('input','',row);file.type='file';file.accept='.pdf,.docx,.txt,.md';const key='profile-upload';file.onchange=()=>{if(file.files[0])files.set(key,file.files[0]);};if(files.has(key))node('p','Selected: '+files.get(key).name,parent);
 const kind=field('Document type',parent,'document-kind',{options:[{value:'cv',label:'CV'},{value:'letter',label:'Cover letter'},{value:'evidence',label:'Supporting evidence'}]});if(!kind.value)kind.value='cv';
 button('Upload and read document',parent,async()=>{const f=file.files[0]||files.get(key);if(!f||!f.size||f.size>10*1024*1024)throw new Error('Choose a nonempty document up to 10 MiB.');const data=await f.arrayBuffer(),digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data))).map(b=>b.toString(16).padStart(2,'0')).join('');const cap=await action('upload_ticket',{filename:f.name,kind:kind.value,sha256:digest,bytes:f.size});const response=await fetch(cap.url,{method:'POST',headers:{'Content-Type':'text/plain'},body:new Blob([cap.ticket+'\n',data]),credentials:'include',redirect:'error'});if(!response.ok)throw new Error('The document was not uploaded. Your selection is retained.');const saved=await response.json();const p=profile.proposal;await action('parse_uploads',p?{id:p.id,upload_ids:[saved.upload_id]}:{upload_ids:[saved.upload_id],base_version:profile.current?.version??null});files.delete(key);},true);
}
async function refresh(force=false){if(!runId||busy)return;busy=true;try{const data=await resource('jobwatch://cards/'+runId+'/'+cardKind+'/'+subjectId),signature=JSON.stringify(data),editing=['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)||document.activeElement?.id==='employer-browser';if(force||(!editing&&signature!==rendered)){render(data);rendered=signature;}}catch{$('status').textContent='This card could not reconnect. Your unsaved answers are retained. Use Refresh to try again.';}finally{busy=false;}}
$('refresh').onclick=()=>refresh(true);$('models').onclick=()=>showCard('models');$('task').onchange=e=>showCard(e.target.value);
app.ontoolresult=async r=>{const value=resultValue(r);runId=value.run_id;cardKind=value.card_kind||'auto';subjectId=value.subject_id||'0';await refresh(true);};app.onhostcontextchanged=c=>{if(c.theme)document.documentElement.style.colorScheme=c.theme;};await app.connect();setInterval(()=>refresh(),5000);setInterval(updateFrame,1500);
function renderModels(models,root){
 const saved=Object.fromEntries(Object.entries(models.roles).map(([role,value])=>[role,value.model]));
 const choices=new Map((models.options||[]).map(option=>[option.id,option]));
 for(const id of Object.values(saved))if(!choices.has(id))choices.set(id,{id,label:id.split('/').at(-1).replaceAll('-',' '),provider:id.split('/')[0],currentOnly:true});
 const settings=section('Your AI models',root);settings.id='model-settings';
 node('p','Use one model for everything, or choose a different model for each task. Your choices apply to new work.',settings,'muted');
 const picker=(label,parent,value,onchange)=>{const row=node('label',label,parent),select=node('select','',row);select.setAttribute('aria-label',label);select.disabled=modelSaving;const placeholder=node('option','Choose a model',select);placeholder.value='';placeholder.disabled=true;
  for(const item of choices.values()){const option=node('option',item.label+' · '+item.provider+(item.currentOnly?' (current)':''),select);option.value=item.id;}
  select.value=value||'';select.onchange=()=>{onchange(select.value);modelNotice='Unsaved changes';message.textContent=modelNotice;save.disabled=false;};return select;};
 const effective={...saved,...modelDraft},all=Object.values(effective),common=all.every(value=>value===all[0])?all[0]:'';
 const main=picker('Model for all tasks',settings,common,value=>{for(const role of Object.keys(saved))modelDraft[role]=value;for(const select of roleSelects)select.value=value;});
 if(!common)main.options[0].textContent='Different models by task';
 const advanced=node('details','',settings);advanced.open=modelSettingsOpen;advanced.ontoggle=()=>{modelSettingsOpen=advanced.open;};node('summary','Choose by task',advanced);
 const roleSelects=[];for(const [role,value] of Object.entries(models.roles))roleSelects.push(picker(value.label,advanced,effective[role],id=>{modelDraft[role]=id;main.value='';}));
 if(!models.catalog_available)node('p','The available model list could not be loaded. Your current choices are shown. Use Refresh to try again.',settings,'notice');
 const message=node('p',modelNotice,settings);message.setAttribute('role','status');
 const save=button('Save models',settings,async()=>{const picks={...modelDraft};if(modelSaving||!Object.keys(picks).length)return;modelSaving=true;message.textContent='Confirm your model choices in LibreChat.';for(const select of [main,...roleSelects])select.disabled=true;try{const result=await action('models',{picks});if(!Object.entries(picks).every(([role,id])=>result.roles?.[role]?.model===id))throw new Error('Your model choices were not saved. Please try again.');modelDraft={};modelNotice='Models saved. New work will use your choices.';message.textContent=modelNotice;}finally{modelSaving=false;for(const select of document.querySelectorAll('#model-settings select'))select.disabled=false;const currentSave=document.querySelector('#model-settings button.primary');if(currentSave)currentSave.disabled=!Object.keys(modelDraft).length;}},true);save.disabled=modelSaving||!Object.keys(modelDraft).length;
}
