import {App} from '@modelcontextprotocol/ext-apps';
const app=new App({name:'Jobwatch',version:'1.0.0'},{}),$=id=>document.getElementById(id);
let runId,rendered,busy=false;
const previews=new Map();
let modelDraft={},modelSettingsOpen=false,modelSaving=false,modelNotice="";
function node(tag,text,parent,cls){const n=document.createElement(tag);n.textContent=text??'';if(cls)n.className=cls;parent.append(n);return n;}
function details(title,value,parent){const d=node('details','',parent);node('summary',title,d);node('pre',typeof value==='string'?value:JSON.stringify(value,null,2),d);return d;}
function section(title,parent=$('body')){const s=node('section','',parent);node('h2',title,s);return s;}
function button(text,parent,fn,primary=false){const b=node('button',text,parent,primary?'primary':'');b.type='button';b.onclick=async()=>{b.disabled=true;try{await fn();await refresh(true);}catch(e){$('status').textContent=e.message;}finally{b.disabled=false;}};return b;}
function resultValue(result){if(result.isError)throw new Error('Jobwatch refused the action. Refresh and review the current state.');if(result._meta?.jobwatch)return result._meta.jobwatch;if(result.structuredContent)return result.structuredContent;return JSON.parse(result.content.find(c=>c.type==='text').text);}
async function action(action,arguments_){return resultValue(await app.callServerTool({name:'jobwatch_action',arguments:{action,arguments:arguments_}}));}
async function resource(uri){const res=await app.readServerResource({uri});return JSON.parse(res.contents.find(c=>c.text!==undefined).text);}
const short=value=>String(value??'').replaceAll('_',' ');
function render({run,profile,models,shortlist,selections=[]}){
 const root=$('body');root.replaceChildren();$('phase').textContent=short(run.state);$('status').textContent=['queued','running'].includes(run.state)?'Jobwatch is working. This panel updates automatically.':'Connected to your saved Jobwatch work.';
 if(run.error)node('p','Jobwatch stopped: '+run.error,root,'notice');
 for(const item of run.interactions.filter(i=>!i.answered)){
  const s=section(item.type==='approval'?'Your decision':'A question for you');
  if(item.type==='approval'){
   node('p',short(item.operation),s);details('Review the exact operation and inputs',item,s).open=true;
   let valid=true;if(item.operation==='profile_confirm'){const c=profile.confirmation,b=item.binding;valid=!!c&&c.proposal_digest===b.proposal_digest&&c.scope_digest===b.scope_digest;details('Profile evidence and search scope',{proposal:profile.proposal,confirmation:c},s).open=true;if(!valid)node('p','The draft changed. Ask Jobwatch for a new confirmation.',s,'notice');}
   if(item.operation==='submit_application')node('p','This sends the application to the employer. Review the exact filled form before confirming.',s,'notice');
   const row=node('div','',s,'row');if(valid)button(item.operation==='submit_application'?'Confirm final Submit':'Approve this operation',row,()=>action('respond',{id:item.id,decision:'approve'}),true);button('Reject',row,()=>action('respond',{id:item.id,decision:'reject'}));
  }else{const label=node('label',item.question||'Your answer',s),input=node('textarea','',label);input.maxLength=4000;const row=node('div','',s,'row');button('Send answer',row,()=>action('respond',{id:item.id,decision:'answer',answer:input.value}),true);button('Decline',row,()=>action('respond',{id:item.id,decision:'decline'}));}
 }
 if(run.result?.answer){const s=section('From Jobwatch');node('div',run.result.answer,s,'answer');}
 if(!profile.current?.version||profile.proposal){
  const s=section(profile.proposal?'Profile draft':'Set up your profile');node('p',profile.proposal?'Review the evidence and answer any gaps.':'Add your CV or supporting evidence. Jobwatch will help you build and confirm your profile before discovery starts.',s);
  if(profile.proposal){const p=profile.proposal;node('p','Draft '+p.revision+' · '+short(p.status),s,'muted');if(p.parse_error)node('p',p.parse_error,s,'notice');for(const q of p.questions||[]){const label=node('label',q.text,s),input=node('textarea','',label);input.maxLength=4000;if(q.why)node('small',q.why,s);button('Save answer',s,()=>action('profile_answer',{id:p.id,expected_revision:p.revision,question_id:q.id,text:input.value}));}details('Evidence and source citations',p.facts,s);
   if(profile.confirmation&&!run.interactions.some(i=>!i.answered&&i.operation==='profile_confirm'&&i.binding?.arguments?.proposal_id===p.id)){const c=profile.confirmation;details('Review profile and discovery scope',c,s);button('Confirm profile and search scope',s,()=>action('profile_confirm',{id:p.id,proposal_digest:c.proposal_digest,scope_digest:c.scope_digest}),true);}}
  upload(s,profile);
 }else{const d=node('details','',root);node('summary','Profile confirmed · add evidence',d);upload(d,profile);}
 for(const entry of shortlist.entries||[]){const c=section(entry.title||entry.posting?.title||'Job '+entry.posting_id);node('p',entry.company||entry.employer||entry.posting?.company||'',c,'muted');node('span',short(entry.label),c,'badge');details('Evidence, uncertainties and ordering',entry,c);}
 for(const outcome of run.result?.outcomes||[])details('Career work outcome',outcome,root);
 documents(run,root);
 for(const selected of selections){const work=section('Application preparation');node('p',short(selected.state)+(selected.error?' · '+selected.error:''),work,'muted');if(selected.run){node('p','Run '+short(selected.run.state),work);if(selected.run.error)node('p',selected.run.error,work,'notice');for(const outcome of selected.run.result?.outcomes||[])details('Preparation outcome',outcome,work);documents(selected.run,work);}if(['pending_dispatch','queued','running'].includes(selected.state))button('Cancel preparation',work,()=>action('cancel_selection',{id:selected.id}));}
 renderModels(models,root);
 const controls=node('div','',root,'row');if(['queued','running','waiting_for_input','waiting_for_approval','interrupted'].includes(run.state))button('Cancel run',controls,()=>action('cancel',{id:run.id}));if(['interrupted','deferred'].includes(run.state))button('Retry retained work',controls,()=>action('retry',{id:run.id}));
}
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
 const save=button('Save models',settings,async()=>{const picks={...modelDraft};if(modelSaving||!Object.keys(picks).length)return;modelSaving=true;message.textContent='Confirm your model choices in LibreChat.';for(const select of [main,...roleSelects])select.disabled=true;try{const result=await action('models',{picks});if(!Object.entries(picks).every(([role,id])=>result.roles?.[role]?.model===id))throw new Error('Your model choices were not saved. Please try again.');modelDraft={};modelNotice='Models saved. New work will use your choices.';}finally{modelSaving=false;for(const select of document.querySelectorAll('#model-settings select'))select.disabled=false;const currentSave=document.querySelector('#model-settings button.primary');if(currentSave)currentSave.disabled=!Object.keys(modelDraft).length;}},true);save.disabled=modelSaving||!Object.keys(modelDraft).length;
}

function documents(run,parent){if(run.artifacts?.length){const s=section('Your documents',parent);for(const artifact of run.artifacts){const c=node('div','',s,'card');node('h3',short(artifact.kind),c);const row=node('div','',c,'row');button('Preview',row,async()=>{const doc=await resource('jobwatch://artifacts/'+artifact.id);previews.set(artifact.id,doc.text);});button('Download',row,async()=>{const value=await action('download_ticket',{id:artifact.id});const opened=await app.openLink({url:value.url});if(opened.isError)throw new Error('Download could not be opened.');});if(previews.has(artifact.id))details('Verified document text',previews.get(artifact.id),c).open=true;}}}
function upload(parent,profile){
 const label=node('label','Choose a document (PDF, DOCX, TXT or MD; up to 10 MiB)',parent),file=node('input','',label);file.type='file';file.accept='.pdf,.docx,.txt,.md';const kl=node('label','Document type',parent),kind=node('select','',kl);for(const [v,t] of [['cv','CV'],['letter','Cover letter'],['evidence','Supporting evidence']]){const o=node('option',t,kind);o.value=v;}
 button('Upload and read document',parent,async()=>{const f=file.files[0];if(!f)throw new Error('Choose a document first.');if(f.size>10*1024*1024||!f.size)throw new Error('Choose a nonempty file up to 10 MiB.');const data=await f.arrayBuffer(),digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data))).map(b=>b.toString(16).padStart(2,'0')).join('');$('status').textContent='Confirm this document upload in LibreChat.';const cap=await action('upload_ticket',{filename:f.name,kind:kind.value,sha256:digest,bytes:f.size});const response=await fetch(cap.url,{method:'POST',headers:{'Content-Type':'text/plain'},body:new Blob([cap.ticket+'\n',data]),credentials:'include',redirect:'error'});if(!response.ok)throw new Error('The upload did not complete. Refresh and try again.');const saved=await response.json();$('status').textContent='Document saved. Confirm reading it to draft your profile.';const p=profile.proposal;await action('parse_uploads',p?{id:p.id,upload_ids:[saved.upload_id]}:{upload_ids:[saved.upload_id],base_version:profile.current?.version??null});},true);
}
async function refresh(force=false){if(!runId||busy)return;busy=true;try{const data=await resource('jobwatch://runs/'+runId),signature=JSON.stringify(data),editing=['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName);if(force||(!editing&&signature!==rendered)){render(data);rendered=signature;}}catch(e){$('status').textContent='Connection interrupted. Use Refresh to reconnect. '+e.message;}finally{busy=false;}}
$('refresh').onclick=()=>refresh(true);$('models').onclick=()=>{$('model-settings')?.scrollIntoView({behavior:'smooth',block:'start'});$('model-settings')?.querySelector('select')?.focus({preventScroll:true});};app.ontoolresult=async r=>{runId=resultValue(r).run_id;await refresh(true);};app.onhostcontextchanged=c=>{if(c.theme)document.documentElement.style.colorScheme=c.theme;};await app.connect();setInterval(()=>refresh(),10000);
