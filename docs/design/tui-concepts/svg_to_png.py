import sys
from playwright.sync_api import sync_playwright
svg=open(sys.argv[1]).read()
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={'width':1400,'height':800})
    pg.set_content('<body style="margin:0;background:#000">'+svg+'</body>')
    pg.screenshot(path=sys.argv[2],full_page=True); b.close()
