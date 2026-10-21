"""Small provider adapters grounded in public DOM, never instructions from HTML."""
from __future__ import annotations

import re
from urllib.parse import urlparse


PAGEUP_ADVERT_HOST = 'careers.pageuppeople.com'
PAGEUP_APPLY_HOSTS = frozenset({'secure.dc2.pageuppeople.com'})


def is_pageup_advert(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and parsed.hostname == PAGEUP_ADVERT_HOST
            and not parsed.username and not parsed.password
            and bool(re.search(r'/[a-z]{2}/job/\d+(?:/|$)', parsed.path)))


def pageup_entry_link(page) -> str | None:
    """One observed PageUp Apply anchor, independent of advert search filters.

    Only the publicly inspected secure DC2 host is supported. This prepares a
    GET destination; it neither clicks a control nor submits a form.
    """
    if not is_pageup_advert(page.url):
        return None
    targets = []
    for anchor in page.query_selector_all('a[href]'):
        label = ' '.join((anchor.text_content() or '').strip().casefold().split())
        if (not anchor.is_visible() or label not in ('apply', 'apply now', 'apply for this job')
                or anchor.get_attribute('onclick') is not None or anchor.get_attribute('download') is not None):
            continue
        target = anchor.evaluate('e => e.href')
        parsed = urlparse(target)
        if (parsed.scheme == 'https' and parsed.hostname in PAGEUP_APPLY_HOSTS
                and not parsed.username and not parsed.password and not parsed.fragment
                and not re.search(r'(?:^|[/_.-])(submit|finalize|finalise)(?:$|[/_.-])', parsed.path.casefold())):
            targets.append(target)
    distinct = list(dict.fromkeys(targets))
    return distinct[0] if len(distinct) == 1 else None


def challenge_provider(url: str) -> str | None:
    """Recognize isolated CAPTCHA frames without reading any response tokens."""
    parsed = urlparse(url)
    host = (parsed.hostname or '').casefold()
    if parsed.scheme != 'https':
        return None
    if host == 'hcaptcha.com' or host.endswith('.hcaptcha.com'):
        return 'hcaptcha'
    if ((host == 'recaptcha.net' or host.endswith('.recaptcha.net')
         or host in ('www.google.com', 'www.recaptcha.net')) and '/recaptcha/' in parsed.path):
        return 'recaptcha'
    return None


def challenge_complete(frame, provider: str) -> bool:
    """Return only completion presence; response token bytes stay in the page.

    The owner completes verification. This read neither solves nor clicks the
    widget, and never returns a response token to Python or a model.
    """
    parent = frame.parent_frame
    if parent is None:
        return False
    names = ['h-captcha-response'] if provider == 'hcaptcha' else ['g-recaptcha-response']
    return parent.evaluate('''names => names.some(name =>
        Array.from(document.querySelectorAll('textarea,input')).some(e =>
            e.name === name && typeof e.value === 'string' && e.value.trim().length > 0))''', names)
