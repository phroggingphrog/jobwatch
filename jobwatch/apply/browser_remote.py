"""Website adapter to the shared native browser owner; standalone boards keep local execution."""
from __future__ import annotations
import base64
import os
from urllib.parse import urlparse
import requests
from fastapi import HTTPException
from jobwatch import users


def call(operation, *, posting_id=None, application_id=None, arguments=None):
    from pipeline.agentic.api import credentials_from_env
    from pipeline.agentic.identity import credentials
    base = os.environ['JOBWATCH_NATIVE_BROWSER_URL'].rstrip('/')
    if urlparse(base).scheme != 'http' or urlparse(base).hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise HTTPException(503, 'browser_configuration_unavailable')
    keys = [key for key,p in {**credentials_from_env(), **credentials()}.items()
            if p.person == users.current() and 'approve' in p.scopes]
    if len(keys) != 1:
        raise HTTPException(503, 'browser_identity_unavailable')
    with requests.Session() as session:
        session.trust_env = False
        response = session.post(base+'/api/agent/browser/website', timeout=120, allow_redirects=False,
            headers={'Authorization':'Bearer '+keys[0]}, json={'operation':operation,
                'posting_id':posting_id,'application_id':application_id,'arguments':arguments or {}})
    if not response.ok:
        raise HTTPException(response.status_code if response.status_code in (400,403,404,409) else 503,
                            'browser_operation_unavailable')
    return response.json()['value']


class RemoteBrowserService:
    def __getattr__(self, name):
        if name in ('auto_fill_ready', 'process_submit_requests', 'settle_open_sessions'):
            return lambda: None  # the native process exclusively owns these loops
        if name in ('context', 'app_context', 'preparation_context'):
            return lambda posting_id, *args: call(name, posting_id=posting_id,
                arguments={'error': args[0]} if args else {})
        if name == 'browser_status':
            return remote_status
        if name == 'settle_submit':
            return lambda posting_id, aid, result=None: call(name, posting_id=posting_id, arguments={'result':result})
        if name == 'answer_missing':
            return lambda posting_id, form: call(name, posting_id=posting_id, arguments={'form':list(form.multi_items())})
        if name == 'start_preparation':
            return lambda posting_id, **kwargs: call(name, posting_id=posting_id, arguments=kwargs)
        if name == 'confirmed_submit':
            return lambda posting_id, confirm, source: call(name, posting_id=posting_id,
                arguments={'confirm':confirm,'source':source})
        raise AttributeError(name)


class RemoteBrowserSessions:
    def _root(self):
        return users.user_dir()
    def status(self, aid):
        return call('manager_status', application_id=aid)
    def open(self, aid, url):
        return call('manager_open', application_id=aid, arguments={'url':url})
    def action(self, aid, action):
        return call('manager_action', application_id=aid, arguments=action)
    def close(self, aid):
        return call('manager_close', application_id=aid)
    def snapshot(self, aid):
        value = call('manager_snapshot', application_id=aid)
        from jobwatch.web.browser_session import BrowserSnapshot
        return BrowserSnapshot(base64.b64decode(value['jpeg']),value['width'],value['height'])
    def close_all(self):
        pass  # closing a frontend must not close the other frontend's browser


def remote_status(aid):
    value = call('manager_status', application_id=aid)
    return {**value, 'open': value.get('state') == 'ready'}
