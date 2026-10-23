'use strict';
const el = id => document.getElementById(id);
let busy = false;
async function api(path, {decision = false, ...options} = {}) {
  const key = el(decision ? 'approval-key' : 'run-key').value;
  if (!key) throw new Error(decision ? 'Enter your decision key.' : 'Enter your chat key.');
  const headers = {Authorization: 'Bearer ' + key};
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(options.body);
  }
  const res = await fetch(path, {...options, headers, cache: 'no-store', redirect: 'error'});
  if (!res.ok) {
    const value = await res.json();
    throw new Error(value.error || value.detail || 'Request failed.');
  }
  return res;
}
function node(tag, text, parent) {
  const element = document.createElement(tag); element.textContent = text; parent.append(element); return element;
}
function button(text, parent, action) {
  const b = node('button', text, parent); b.type = 'button';
  b.onclick = async () => { b.disabled = true; try { await action(); await refresh(); }
    catch (error) { el('status').textContent = error.message; } finally { b.disabled = false; } };
}
async function refresh() {
  if (busy) return;
  busy = true;
  try {
    const value = await (await api('/api/agent/client/runs')).json();
    const list = el('runs'); list.replaceChildren();
    for (const run of value.runs) {
      const article = node('article', '', list); article.id = 'run=' + run.id;
      node('h3', run.state + ' · ' + run.id, article);
      if (run.error) node('p', run.error, article);
      if (run.result?.answer) node('pre', run.result.answer, article);
      for (const item of run.interactions.filter(i => !i.answered)) {
        node('pre', JSON.stringify(item, null, 2), article);
        const path = '/api/agent/interactions/' + encodeURIComponent(item.id) + '/responses';
        const send = body => api(path, {method: 'POST', decision: true, body});
        if (item.type === 'approval') {
          if (item.operation === 'profile_confirm') {
            const proposalId = item.binding?.arguments?.proposal_id;
            const prefix = '/api/agent/profile/proposals/' + encodeURIComponent(proposalId);
            const proposal = await (await api(prefix)).json();
            const shown = await (await api(prefix + '/confirmation')).json();
            node('pre', JSON.stringify({profile: proposal, confirmation: shown}, null, 2), article);
            if (shown.proposal_digest !== item.binding.proposal_digest || shown.scope_digest !== item.binding.scope_digest) {
              node('p', 'The profile or search scope changed. Ask Jobwatch for a new confirmation.', article);
              continue;
            }
          }
          if (item.operation === 'submit_application')
            node('p', 'This sends the application to the employer. Review the filled form on the Jobwatch board before approving.', article);
          button('Approve this exact operation', article, () => send({decision: 'approve'}));
          button('Reject', article, () => send({decision: 'reject'}));
        } else {
          const label = node('label', item.question || 'Your answer', article);
          const answer = node('textarea', '', label); answer.maxLength = 4000;
          button('Send answer', article, () => send({decision: 'answer', answer: answer.value}));
          button('Decline to answer', article, () => send({decision: 'decline'}));
        }
      }
      for (const artifact of run.artifacts) button('Download ' + artifact.kind, article, async () => {
        const response = await api(artifact.url);
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement('a'); link.href = url;
        link.download = artifact.kind + (artifact.kind === 'form_map' ? '.json' : '.pdf'); link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      });
      if (['queued','running','waiting_for_input','waiting_for_approval','interrupted'].includes(run.state))
        button('Cancel run', article, () => api('/api/agent/runs/' + run.id + '/cancel', {method: 'POST'}));
      if (['interrupted','deferred'].includes(run.state))
        button('Retry retained run', article, () => api('/api/agent/runs/' + run.id + '/retry', {method: 'POST'}));
    }
    if (!value.runs.length) node('p', 'No work yet. Start a conversation with Jobwatch in LibreChat.', list);
    el('status').textContent = 'Connected. Refresh to see new progress.';
  } catch (error) { el('status').textContent = error.message; }
  finally { busy = false; }
}
el('connect').onclick = refresh;
el('upload').onclick = async () => {
  try {
    const file = el('file').files[0]; if (!file) throw new Error('Choose a document.');
    const data = new FormData(); data.append('file', file); data.append('kind', el('kind').value);
    const uploaded = await (await api('/api/agent/profile/uploads', {method: 'POST', body: data})).json();
    el('uploaded').textContent = 'Uploaded. Tell Jobwatch in LibreChat: Use upload ' + uploaded.upload_id + ' to start my profile.';
  } catch (error) { el('status').textContent = error.message; }
};
