import {build} from 'esbuild';
import {readFileSync, writeFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
const result = await build({entryPoints:['app.js'],bundle:true,minify:true,format:'esm',write:false});
const html = readFileSync('panel.html','utf8').replace('/* APP_BUNDLE */', () => result.outputFiles[0].text.replace(/<\/script/gi, '<\\/script'));
const script = html.split('<script type="module">')[1].split('</script>')[0];
execFileSync(process.execPath, ['--input-type=module', '--check'], {input: script});
writeFileSync('../../pipeline/agentic/jobwatch-app.html', html);
