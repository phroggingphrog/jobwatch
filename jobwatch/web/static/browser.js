(() => {
  'use strict';
  const image = document.getElementById('application-browser');
  if (!image) return;
  const notice = document.getElementById('browser-control-message');
  let pending = Promise.resolve();
  function send(action) {
    if (document.getElementById('preparation-status')?.dataset.automationActive === 'true') {
      notice.textContent = 'Jobwatch is filling the application. Controls return when it finishes.';
      return;
    }
    pending = pending.then(async () => {
      const response = await fetch(image.dataset.actionUrl, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(action)
      });
      notice.textContent = response.ok ? '' : 'Browser control is temporarily unavailable.';
    }).catch(() => { notice.textContent = 'Connection interrupted. Refresh to reconnect.'; });
  }
  image.addEventListener('click', event => {
    image.focus();
    const rect = image.getBoundingClientRect();
    send({kind: 'click', x: Math.round((event.clientX - rect.left) * image.naturalWidth / rect.width),
          y: Math.round((event.clientY - rect.top) * image.naturalHeight / rect.height)});
  });
  image.addEventListener('keydown', event => {
    event.stopPropagation();
    if (event.key === 'v' && (event.ctrlKey || event.metaKey)) return;
    event.preventDefault();
    if (event.key.length === 1 && !event.ctrlKey && !event.metaKey) send({kind: 'type', text: event.key});
    else {
      const allowed = ['Tab','Enter','Backspace','Delete','Escape','ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','PageUp','PageDown'];
      if (allowed.includes(event.key)) send({kind: 'key', key: (event.shiftKey ? 'Shift+' : '') + event.key});
      else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') send({kind: 'key', key: 'Control+A'});
    }
  });
  image.addEventListener('paste', event => { event.preventDefault(); send({kind: 'type', text: event.clipboardData.getData('text/plain')}); });
  image.addEventListener('wheel', event => { event.preventDefault(); send({kind: 'scroll', dx: Math.round(event.deltaX), dy: Math.round(event.deltaY)}); }, {passive: false});
})();
