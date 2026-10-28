(function () {
  var form = document.getElementById('models-form');
  if (!form) return;
  form.querySelectorAll('.mrow').forEach(function (row) {
    row.querySelector('[data-test]').addEventListener('click', function (e) {
      var out = row.querySelector('[data-result]'), btn = e.currentTarget;
      out.className = 'mres'; out.textContent = 'Testing...'; btn.disabled = true;
      fetch('/models/test', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({role: row.dataset.role})})
        .then(function (r) { return r.json(); })
        .then(function (d) {
          out.className = 'mres ' + (d.ok ? 'ok' : 'bad');
          out.textContent = d.ok ? 'OK: ' + d.model + ' answered "' + d.text + '"' : 'Error: ' + d.error;
        })
        .catch(function () { out.className = 'mres bad'; out.textContent = 'Error: could not reach Jobwatch'; })
        .then(function () { btn.disabled = false; });
    });
  });
})();
