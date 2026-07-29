import os
from playwright.sync_api import sync_playwright
HERE=os.path.dirname(os.path.abspath(__file__))
CHROME=os.environ.get("CHROME_BIN","/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
src="file://"+os.path.join(HERE,"report.html")
out=os.path.join(HERE,"report.png")
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=CHROME if os.path.exists(CHROME) else None,
                        args=["--no-sandbox"])
    pg=b.new_page(viewport={"width":960,"height":900},device_scale_factor=2)
    pg.goto(src); pg.wait_for_timeout(400)
    el=pg.query_selector("body > div")
    (el.screenshot(path=out) if el else pg.screenshot(path=out,full_page=True))
    b.close()
print("wrote",out)
