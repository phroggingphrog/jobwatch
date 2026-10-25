"""Stage 1 of the ChatGPT connector: read-only tools plus MCP Apps widgets.

Tools only read. Submit, prepare and revise are not here (stages 2 and 3). Every read runs as the
authenticated person; no tool argument names a person. Reuses task_state, the same service the
chat agent's own jobs_overview / task_status tools call.
"""
from __future__ import annotations

import json
import sqlite3
from urllib.parse import urlparse

from fastmcp import FastMCP
from fastmcp.tools import ToolResult

from jobwatch import users
from jobwatch.config import load_config
from pipeline.agentic import task_state
from pipeline.agentic.chat import job_connection
from pipeline.agentic.runtime import RuntimeErrorSafe

MIME = 'text/html;profile=mcp-app'
LIST_URI = 'ui://jobwatch/chatgpt-jobs-v1.html'
DETAIL_URI = 'ui://jobwatch/chatgpt-job-v1.html'
READ_ONLY = {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False, 'idempotentHint': True}
# The widgets are self-contained: no external scripts, styles or fonts, and they only call this server.
CSP = {'connectDomains': [], 'resourceDomains': []}

_COUNT_TEXT = (('needs_you', 'need you'), ('needs_info', 'need info'), ('outcome_unknown', 'outcome unknown'),
               ('submitted', 'submitted'))


def counts_text(counts: dict) -> str:
    parts = [f'{counts[key]} {label}' for key, label in _COUNT_TEXT if counts.get(key)]
    return ' · '.join(parts) or 'Nothing needs you'


def _http_url(url) -> str | None:
    parsed = urlparse(url or '')
    return url if parsed.scheme in ('http', 'https') and parsed.netloc else None


def _list(value) -> list[str]:
    try:
        items = json.loads(value) if value else []
    except ValueError:
        return []
    return [str(i)[:300] for i in items if isinstance(i, (str, int, float))][:8] if isinstance(items, list) else []


def overview(person: str, limit: int = 50) -> dict:
    limit = max(1, min(int(limit), 100))
    with users.use(person), job_connection(load_config()) as conn:
        rows = task_state.jobs_overview(conn, limit)
    return {'view': 'list', 'counts': task_state.overview_counts(rows), 'jobs': rows}


def detail(person: str, posting_id: int) -> dict:
    if type(posting_id) is not int or posting_id < 1:
        raise RuntimeErrorSafe('invalid_request')
    with users.use(person), job_connection(load_config()) as conn:
        conn.row_factory = sqlite3.Row
        post = conn.execute('SELECT title, company, location, url FROM postings WHERE id=?', (posting_id,)).fetchone()
        if post is None:
            return {'view': 'detail', 'posting_id': posting_id, 'found': False}
        has = lambda t: bool(conn.execute('SELECT 1 FROM sqlite_master WHERE name=?', (t,)).fetchone())
        review = conn.execute('SELECT score, reason, pros_json, cons_json FROM ad_reviews WHERE posting_id=?',
                              (posting_id,)).fetchone() if has('ad_reviews') else None
        card = task_state.task_card(conn, posting_id)
        draft = conn.execute('SELECT d.version FROM drafts d JOIN applications a ON a.id=d.application_id '
                             "WHERE a.posting_id=? AND d.status='ready' ORDER BY d.version DESC LIMIT 1",
                             (posting_id,)).fetchone() if has('drafts') and has('applications') else None
    return {'view': 'detail', 'posting_id': posting_id, 'found': True, 'employer': post['company'],
            'title': post['title'], 'location': post['location'], 'ad_url': _http_url(post['url']),
            'score': review['score'] if review else None, 'why_it_fits': (review['reason'] if review else None),
            'pros': _list(review['pros_json']) if review else [], 'cons': _list(review['cons_json']) if review else [],
            'state': card['state'], 'state_detail': card.get('message') or (card.get('submit') or {}).get('reason') or '',
            'documents_ready': draft is not None, 'draft_version': draft['version'] if draft else None}


def _overview_text(data: dict) -> str:
    lines = [f"{counts_text(data['counts'])}. {len(data['jobs'])} jobs with activity."]
    lines += [f"#{j['posting_id']} {j['employer'] or '?'} - {j['title'] or '?'}: {j['state']}" for j in data['jobs'][:10]]
    return '\n'.join(lines)


def _detail_text(d: dict) -> str:
    if not d['found']:
        return f"No job {d['posting_id']} found."
    docs = 'documents ready' if d['documents_ready'] else 'no documents ready'
    score = f", score {d['score']}" if d['score'] is not None else ''
    return f"#{d['posting_id']} {d['employer'] or '?'} - {d['title'] or '?'}{score}. State: {d['state']}; {docs}."


def register(server: FastMCP, person_from_request) -> None:
    """Add the read-only tools and widget resources to an authenticated server."""

    @server.tool(name='jobs_overview', title='Jobs overview', annotations=READ_ONLY, meta={
        'ui': {'resourceUri': LIST_URI}, 'openai/outputTemplate': LIST_URI,
        'openai/toolInvocation/invoking': 'Reading your jobs', 'openai/toolInvocation/invoked': 'Jobs ready'})
    def jobs_overview_tool(limit: int = 50) -> ToolResult:
        """List the person's jobs with activity (newest first) with a plain state for each and counts of
        what needs them. Read-only. 'draft ready' is never 'submitted'."""
        data = overview(person_from_request(), limit)
        return ToolResult(content=_overview_text(data), structured_content=data)

    @server.tool(name='job_detail', title='Job detail', annotations=READ_ONLY, meta={
        'ui': {'resourceUri': DETAIL_URI}, 'openai/outputTemplate': DETAIL_URI,
        'openai/toolInvocation/invoking': 'Reading the job', 'openai/toolInvocation/invoked': 'Job ready'})
    def job_detail_tool(posting_id: int) -> ToolResult:
        """Employer, title, score, why it fits, state, whether documents are ready, and the ad link for one job.
        Read-only."""
        data = detail(person_from_request(), posting_id)
        return ToolResult(content=_detail_text(data), structured_content=data)

    @server.tool(name='task_status', title='Task status', annotations=READ_ONLY)
    def task_status_tool(posting_id: int) -> ToolResult:
        """Plain state of the work on a posting: queued, drafting, draft ready, awaiting browser press, executing,
        submitted, outcome unknown, failed, cancelled, not started. Read-only."""
        if type(posting_id) is not int or posting_id < 1:
            raise RuntimeErrorSafe('invalid_request')
        with users.use(person_from_request()), job_connection(load_config()) as conn:
            card = task_state.task_card(conn, posting_id)
        return ToolResult(content=f"#{posting_id}: {card['state']}." + (' ' + card['message'] if card.get('message') else ''),
                          structured_content=card)

    for uri, name in ((LIST_URI, 'Jobwatch jobs list'), (DETAIL_URI, 'Jobwatch job detail')):
        server.resource(uri, name=name, mime_type=MIME,
                        meta={'ui': {'prefersBorder': True, 'csp': CSP}})(lambda: WIDGET_HTML)


WIDGET_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>Jobwatch</title>
<style>
:root{--bg:#fff;--fg:#1a1d21;--muted:#4b5563;--line:#d5d9e0;--card:#f5f6f8;--focus:#1d4ed8;
--warn:#8a3b00;--warnbg:#fff1e3;--bad:#9b1c1c;--badbg:#fde8e8;--ok:#14532d;--okbg:#e3f5e8;--info:#1e3a8a;--infobg:#e6edfd}
@media (prefers-color-scheme:dark){:root{--bg:#14171b;--fg:#eceef2;--muted:#aab2bf;--line:#363c46;--card:#1d2127;--focus:#8ab4ff;
--warn:#ffc78a;--warnbg:#3a2a16;--bad:#ffb4b4;--badbg:#401c1c;--ok:#a6e8b9;--okbg:#17321f;--info:#b6ccff;--infobg:#1f2c4d}}
*{box-sizing:border-box}
body{margin:0;padding:12px;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
h1{font-size:17px;margin:0 0 2px}h2{font-size:15px;margin:14px 0 4px}
.sub{color:var(--muted);margin:0 0 10px}
ul{list-style:none;margin:0;padding:0;border:1px solid var(--line);border-radius:8px;overflow:hidden}
li+li{border-top:1px solid var(--line)}
.row{display:flex;gap:10px;align-items:center;width:100%;padding:10px 12px;background:var(--card);color:inherit;border:0;
font:inherit;text-align:left;cursor:pointer;min-height:44px}
.row:hover{filter:brightness(.97)}
:focus-visible{outline:3px solid var(--focus);outline-offset:-3px}
.grow{flex:1;min-width:0}.t{font-weight:600;overflow-wrap:anywhere}.e{color:var(--muted);font-size:13px}
.badge{display:inline-flex;gap:4px;align-items:center;white-space:nowrap;border:1px solid currentColor;border-radius:999px;
padding:1px 9px;font-size:12px;font-weight:600}
.b-warn{color:var(--warn);background:var(--warnbg)}.b-bad{color:var(--bad);background:var(--badbg)}
.b-ok{color:var(--ok);background:var(--okbg)}.b-info{color:var(--info);background:var(--infobg)}
.score{font-variant-numeric:tabular-nums;color:var(--muted);font-size:13px}
button.back,a.ad{font:inherit;color:var(--focus);background:none;border:0;padding:6px 0;cursor:pointer;text-decoration:underline;min-height:32px}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:8px 0}dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}
.pc{margin:4px 0;padding-left:20px;list-style:disc;border:0}.pc li{border:0;padding:1px 0}
.note{border:1px solid var(--line);border-radius:8px;padding:8px 10px;background:var(--card);margin:8px 0}
.slot{margin-top:12px}
h1[tabindex]:focus{outline:none}
</style></head><body>
<main id="app" aria-live="polite"><h1>Jobwatch</h1><p class="sub">Loading...</p></main>
<script>
(function(){
var app=document.getElementById('app'),pending={},nextId=1,listData=null,lastFocus=null;
function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e}
var BADGE={'draft ready':['b-warn','*'],'awaiting browser press':['b-warn','*'],'failed':['b-bad','x'],'expired':['b-bad','x'],
'outcome unknown':['b-bad','?'],'submitted':['b-ok','+'],'queued':['b-info','...'],'drafting':['b-info','...'],'executing':['b-info','...'],
'cancelled':['b-info','-'],'not started':['b-info','o']};
function badge(state){var b=BADGE[state]||['b-info','o'],s=el('span','badge '+b[0]);s.appendChild(el('span',null,b[1])).setAttribute('aria-hidden','true');s.appendChild(document.createTextNode(state));return s}
function request(method,params){var id=nextId++;window.parent.postMessage({jsonrpc:'2.0',id:id,method:method,params:params},'*');
return new Promise(function(res,rej){pending[id]={res:res,rej:rej};setTimeout(function(){if(pending[id]){delete pending[id];rej(new Error('timeout'))}},20000)})}
function callTool(name,args){
if(window.openai&&window.openai.callTool)return window.openai.callTool(name,args);
return request('tools/call',{name:name,arguments:args})}
function sc(r){return r&&(r.structuredContent||(r.result&&r.result.structuredContent))||null}
var COUNTS=[['needs_you','need you'],['needs_info','need info'],['outcome_unknown','outcome unknown'],['submitted','submitted']];
function countsText(c){var p=[];COUNTS.forEach(function(k){if(c&&c[k[0]])p.push(c[k[0]]+' '+k[1])});return p.join(' · ')||'Nothing needs you'}
function renderList(d){listData=d;app.textContent='';
app.appendChild(el('h1',null,'Your jobs'));app.appendChild(el('p','sub',countsText(d.counts)));
if(!d.jobs||!d.jobs.length){app.appendChild(el('p',null,'No jobs with activity yet.'));return}
var ul=el('ul');d.jobs.forEach(function(j){var li=el('li'),b=el('button','row');b.type='button';
b.setAttribute('aria-label',(j.employer||'Unknown employer')+', '+(j.title||'untitled')+', '+j.state+'. Open details.');
var g=el('span','grow');g.appendChild(el('div','t',j.title||'(untitled)'));g.appendChild(el('div','e',j.employer||'Unknown employer'));
b.appendChild(g);if(j.score!=null)b.appendChild(el('span','score','Score '+j.score));b.appendChild(badge(j.state));
b.addEventListener('click',function(){open(j.posting_id,b)});li.appendChild(b);ul.appendChild(li)});app.appendChild(ul)}
function open(id,from){lastFocus=from||null;app.setAttribute('aria-busy','true');
callTool('job_detail',{posting_id:id}).then(function(r){var d=sc(r);if(d)renderDetail(d,true);else fail()},fail)}
function fail(){app.removeAttribute('aria-busy');app.appendChild(el('p','note','Could not load that job. Try again.'))}
function renderDetail(d,fromList){app.removeAttribute('aria-busy');app.textContent='';
if(fromList&&listData){var back=el('button','back','Back to jobs');back.type='button';back.addEventListener('click',function(){renderList(listData);
var rows=app.querySelectorAll('button.row');for(var i=0;i<rows.length;i++){if(lastFocus&&rows[i].getAttribute('aria-label')===lastFocus.getAttribute('aria-label')){rows[i].focus();break}}});app.appendChild(back)}
if(!d.found){app.appendChild(el('p',null,'That job was not found.'));return}
var h=el('h1',null,d.title||'(untitled)');h.tabIndex=-1;app.appendChild(h);app.appendChild(el('p','sub',(d.employer||'Unknown employer')+(d.location?' · '+d.location:'')));
var dl=el('dl');function row(k,v){dl.appendChild(el('dt',null,k));var dd=el('dd');if(typeof v==='string')dd.textContent=v;else dd.appendChild(v);dl.appendChild(dd)}
row('State',badge(d.state));if(d.state_detail)row('Detail',d.state_detail);
row('Score',d.score!=null?String(d.score):'Not scored');
row('Documents',d.documents_ready?'Ready'+(d.draft_version?' (draft v'+d.draft_version+')':''):'None ready');app.appendChild(dl);
if(d.why_it_fits){app.appendChild(el('h2',null,'Why it fits'));app.appendChild(el('p',null,d.why_it_fits))}
[['pros','In its favour'],['cons','Against']].forEach(function(k){if(d[k[0]]&&d[k[0]].length){app.appendChild(el('h2',null,k[1]));
var ul=el('ul','pc');d[k[0]].forEach(function(t){ul.appendChild(el('li',null,t))});app.appendChild(ul)}});
if(d.ad_url&&/^https?:\/\//.test(d.ad_url)){var a=el('a','ad','Open the job ad');a.href=d.ad_url;a.target='_blank';a.rel='noopener noreferrer';app.appendChild(a)}
/* STAGE 2/3 SLOT: prepare / revise (stage 2) and the Submit button (stage 3) go here. Stage 1 is read-only: no buttons. */
var slot=el('div','slot');slot.id='actions-slot';slot.hidden=true;app.appendChild(slot);
h.focus()}
function show(d){if(!d)return;if(d.view==='detail')renderDetail(d,false);else if(d.view==='list')renderList(d)}
window.addEventListener('message',function(ev){if(ev.source!==window.parent)return;var m=ev.data;if(!m||m.jsonrpc!=='2.0')return;
if(m.id!==undefined&&pending[m.id]){var p=pending[m.id];delete pending[m.id];m.error?p.rej(m.error):p.res(m.result);return}
if(m.method==='ui/notifications/tool-result')show(m.params&&m.params.structuredContent)},{passive:true});
window.addEventListener('openai:set_globals',function(){if(window.openai&&window.openai.toolOutput)show(window.openai.toolOutput)});
if(window.openai&&window.openai.toolOutput)show(window.openai.toolOutput);
else request('ui/initialize',{appInfo:{name:'jobwatch',version:'1'},appCapabilities:{},protocolVersion:'2025-06-18'}).then(function(){
window.parent.postMessage({jsonrpc:'2.0',method:'ui/notifications/initialized',params:{}},'*')},function(){});
window.__show=show;
})();
</script></body></html>
"""
