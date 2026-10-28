"""Connect accounts: status comes from sign-in cookie names in the browser profile (synthetic cookies only)."""
import sqlite3
import time

from jobwatch.web.accounts_routes import connected_sites, profile_path


def test_connected_sites_reads_cookie_names_only(tmp_path):
    cookies = profile_path(tmp_path) / 'Default' / 'Network' / 'Cookies'
    cookies.parent.mkdir(parents=True)
    db = sqlite3.connect(cookies)
    db.execute('create table cookies (host_key text, name text, expires_utc integer)')
    future = int((time.time() + 11644473600 + 86400) * 1_000_000)
    db.executemany('insert into cookies values (?,?,?)', [
        ('.linkedin.com', 'li_at', future),   # signed in
        ('.seek.com.au', 'sol_id', 1),        # expired
        ('.indeed.com', 'other', future)])    # not a sign-in cookie
    db.commit(); db.close()
    assert connected_sites(tmp_path) == {'seek': False, 'linkedin': True, 'indeed': False}
    assert not any(connected_sites(tmp_path / 'nothing').values())
