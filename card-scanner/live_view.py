#!/usr/bin/env python3
"""Live view of the most recent ESP32-CAM scan, for framing/focus setup.

Run on the Pi:
    python3 live_view.py
Then open  http://<pi-ip>:8000/  in your computer's browser.

It shows the newest non-empty JPEG the camera POSTed to /scan, auto-refreshing
every ~1s, plus the latest recognition result (match + price, or the no-match
reason) read from the app's display_state.json. Ctrl+C to stop.
"""
import glob
import json
import os
import socketserver
import time
from http.server import BaseHTTPRequestHandler

SCANS = os.path.expanduser("~/card-scanner/data/scans")
PORT = 8000

_state_path = None


def find_state():
    """Locate display_state.json once; the app writes it every scan."""
    global _state_path
    if _state_path and os.path.exists(_state_path):
        return _state_path
    cands = glob.glob(os.path.expanduser("~/card-scanner/**/display_state.json"),
                      recursive=True)
    _state_path = cands[0] if cands else None
    return _state_path


def newest_nonempty():
    files = sorted(glob.glob(os.path.join(SCANS, "*.jpg")),
                   key=os.path.getmtime, reverse=True)
    for f in files:
        try:
            if os.path.getsize(f) > 0:
                return f
        except OSError:
            continue
    return None


PAGE = b"""<!doctype html><html><head><meta charset="utf-8">
<title>Card scanner - live view</title>
<style>
 body{margin:0;background:#0b0f14;color:#e8eef5;font-family:system-ui,sans-serif;text-align:center}
 #info{padding:10px;font-size:15px;letter-spacing:.2px}
 #result{font-weight:600}
 .ok{color:#5fd08a}.no{color:#f2a65a}
 img{max-width:100vw;max-height:82vh;object-fit:contain;background:#000}
 small{color:#8aa0b4}
</style></head><body>
<div id="info"><span id="result">waiting for first scan...</span><br>
<small id="meta"></small></div>
<img id="v" src="/latest.jpg" alt="latest scan">
<script>
async function tick(){
 try{
  const r=await fetch('/meta',{cache:'no-store'});
  const m=await r.json();
  const res=document.getElementById('result');
  const meta=document.getElementById('meta');
  if(!m.file){res.textContent='no scans yet';meta.textContent='';return;}
  if(m.matched){res.textContent='MATCH: '+m.card+'  '+m.price;res.className='ok';}
  else{res.textContent='no match ('+(m.reason||'')+')';res.className='no';}
  meta.textContent=m.file+'  -  '+m.size+' bytes  -  '+m.age+'s ago';
  document.getElementById('v').src='/latest.jpg?t='+Date.now();
 }catch(e){}
}
setInterval(tick,1000); tick();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, "text/html", PAGE)
            return
        if self.path == "/meta":
            self._send(200, "application/json", self._meta())
            return
        if self.path.startswith("/latest.jpg"):
            f = newest_nonempty()
            if not f:
                self._send(404, "text/plain", b"no image")
                return
            try:
                with open(f, "rb") as fh:
                    data = fh.read()
            except OSError:
                self._send(404, "text/plain", b"read error")
                return
            self._send(200, "image/jpeg", data)
            return
        self._send(404, "text/plain", b"not found")

    def _meta(self):
        f = newest_nonempty()
        info = {}
        if f:
            info = {
                "file": os.path.basename(f),
                "size": os.path.getsize(f),
                "age": int(time.time() - os.path.getmtime(f)),
                "matched": False,
                "reason": "",
                "card": "",
                "price": "",
            }
            sp = find_state()
            if sp:
                try:
                    with open(sp) as fh:
                        st = json.load(fh)
                    info["matched"] = bool(st.get("matched"))
                    info["reason"] = st.get("reason", "")
                    info["card"] = st.get("card_name", "")
                    p = st.get("price")
                    info["price"] = (f"${p}" if p is not None else "")
                except Exception:
                    pass
        return json.dumps(info).encode()

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("", PORT), H) as s:
        print(f"Live view on http://0.0.0.0:{PORT}/   (Ctrl+C to stop)")
        s.serve_forever()
