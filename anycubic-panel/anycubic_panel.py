#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import random
import re
import shutil
import socket
import ssl
import string
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PRINTER_IP = os.environ.get("ANYCUBIC_IP", "192.168.1.144")
MODEL_ID = os.environ.get("ANYCUBIC_MODEL_ID", "20029")
PANEL_HOST = os.environ.get("PANEL_HOST", "127.0.0.1")
PANEL_PORT = int(os.environ.get("PANEL_PORT", "8765"))


def md5_hex(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def now_ms():
    return int(time.time() * 1000)


def enc_str(value):
    data = value.encode("utf-8")
    return struct.pack("!H", len(data)) + data


def mqtt_remaining_length(length):
    out = bytearray()
    while True:
        byte = length % 128
        length //= 128
        if length:
            byte |= 128
        out.append(byte)
        if not length:
            return bytes(out)


def mqtt_packet(packet_type, payload):
    return bytes([packet_type]) + mqtt_remaining_length(len(payload)) + payload


def recv_exact(sock, count):
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise EOFError("connection closed")
        data += chunk
    return data


def recv_packet(sock):
    first = sock.recv(1)
    if not first:
        return None, b""
    multiplier = 1
    length = 0
    while True:
        byte = recv_exact(sock, 1)[0]
        length += (byte & 127) * multiplier
        if not byte & 128:
            break
        multiplier *= 128
    return first[0], recv_exact(sock, length)


class MqttClient:
    def __init__(self, creds):
        self.creds = creds
        self.sock = None

    def __enter__(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.load_cert_chain(self.creds["cert_path"], self.creds["key_path"])
        raw = socket.create_connection((PRINTER_IP, 9883), timeout=10)
        self.sock = context.wrap_socket(raw, server_hostname=PRINTER_IP)
        self.sock.settimeout(12)
        client_id = "panel-" + "".join(random.choice(string.ascii_letters + string.digits) for _ in range(8))
        variable = enc_str("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", 60)
        payload = enc_str(client_id) + enc_str(self.creds["username"]) + enc_str(self.creds["password"])
        self.sock.sendall(mqtt_packet(0x10, variable + payload))
        packet_type, data = recv_packet(self.sock)
        if packet_type != 0x20 or len(data) < 2 or data[1] != 0:
            raise RuntimeError(f"MQTT connect failed: {packet_type!r} {data.hex()}")
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.sock:
                self.sock.sendall(mqtt_packet(0xE0, b""))
                self.sock.close()
        finally:
            self.sock = None

    def subscribe(self, topic, packet_id=1):
        payload = struct.pack("!H", packet_id) + enc_str(topic) + b"\x00"
        self.sock.sendall(mqtt_packet(0x82, payload))
        packet_type, data = recv_packet(self.sock)
        if packet_type != 0x90:
            raise RuntimeError(f"MQTT subscribe failed: {packet_type!r} {data.hex()}")

    def publish(self, topic, obj):
        payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        self.sock.sendall(mqtt_packet(0x30, enc_str(topic) + payload))

    def read_publishes(self, seconds=10):
        deadline = time.time() + seconds
        messages = []
        while time.time() < deadline:
            try:
                packet_type, data = recv_packet(self.sock)
            except socket.timeout:
                break
            if packet_type is None:
                break
            if packet_type >> 4 != 3:
                continue
            topic_len = struct.unpack("!H", data[:2])[0]
            topic = data[2 : 2 + topic_len].decode("utf-8", "replace")
            payload = data[2 + topic_len :]
            try:
                parsed = json.loads(payload.decode("utf-8"))
            except Exception:
                parsed = payload.decode("utf-8", "replace")
            messages.append({"topic": topic, "payload": parsed})
        return messages


class Printer:
    def __init__(self):
        self.lock = threading.Lock()
        self.info = {}
        self.creds = {}
        self.temp_dir = tempfile.mkdtemp(prefix="anycubic-panel-")
        self.refresh()

    def fetch_info(self):
        with urllib.request.urlopen(f"http://{PRINTER_IP}:18910/info", timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def refresh(self):
        with self.lock:
            self.info = self.fetch_info()
            self.creds = self.fetch_ctrl_info(self.info)
            cert_path = os.path.join(self.temp_dir, "client.crt")
            key_path = os.path.join(self.temp_dir, "client.key")
            with open(cert_path, "w", encoding="utf-8") as handle:
                handle.write(self.creds["devicecrt"])
            with open(key_path, "w", encoding="utf-8") as handle:
                handle.write(self.creds["devicepk"])
            self.creds["cert_path"] = cert_path
            self.creds["key_path"] = key_path
            return self.safe_info()

    def fetch_ctrl_info(self, info):
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            raise RuntimeError("PowerShell is required for AES-CBC decrypt on this Windows panel")
        script = r'''
$ip=$env:ANYCUBIC_PS_IP; $cn=$env:ANYCUBIC_PS_CN; $token=$env:ANYCUBIC_PS_TOKEN
function Md5Hex([string]$s) {
  $md5=[System.Security.Cryptography.MD5]::Create()
  -join ($md5.ComputeHash([Text.Encoding]::UTF8.GetBytes($s)) | ForEach-Object { $_.ToString('x2') })
}
$nonce='panel' + (Get-Random -Minimum 1000000000 -Maximum 1999999999)
$ts=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds().ToString()
$inner=Md5Hex $token.Substring(0,16)
$sign=Md5Hex ($inner + $ts + $nonce)
$url="http://$ip`:18910/ctrl?ts=$ts&nonce=$nonce&did=$cn&sign=$sign"
$resp=Invoke-RestMethod -Uri $url -Method Post -Body '{}' -ContentType 'application/json' -TimeoutSec 10
$key=[Text.Encoding]::UTF8.GetBytes($token.Substring(16,16))
$iv=[Text.Encoding]::UTF8.GetBytes([string]$resp.data.token)
$cipher=[Convert]::FromBase64String([string]$resp.data.info)
$aes=[System.Security.Cryptography.Aes]::Create()
$aes.Mode=[System.Security.Cryptography.CipherMode]::CBC
$aes.Padding=[System.Security.Cryptography.PaddingMode]::PKCS7
$aes.Key=$key
$aes.IV=$iv
$plain=[Text.Encoding]::UTF8.GetString($aes.CreateDecryptor().TransformFinalBlock($cipher,0,$cipher.Length))
$plain
'''
        env = os.environ.copy()
        env["ANYCUBIC_PS_IP"] = info["ip"]
        env["ANYCUBIC_PS_CN"] = info["cn"]
        env["ANYCUBIC_PS_TOKEN"] = info["token"]
        result = subprocess.run(
            [powershell, "-NoProfile", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )
        return json.loads(result.stdout)

    def safe_info(self):
        printer_info = dict(self.info)
        printer_info.pop("token", None)
        if "fileUploadurl" in printer_info:
            printer_info["fileUploadurl"] = "available"
        return {
            "printer": printer_info,
            "ctrl": {
                "broker": self.creds.get("broker"),
                "deviceId": self.creds.get("deviceId"),
                "username": self.creds.get("username"),
            },
        }

    def command_topic(self, source, kind):
        return f"anycubic/anycubicCloud/v1/{source}/printer/{MODEL_ID}/{self.creds['deviceId']}/{kind}"

    def report_topic(self):
        return f"anycubic/anycubicCloud/v1/printer/public/{MODEL_ID}/{self.creds['deviceId']}/#"

    def publish(self, source, kind, payload):
        with MqttClient(self.creds) as client:
            client.publish(self.command_topic(source, kind), payload)

    def status(self):
        msg_id = str(uuid.uuid4())
        payload = {"type": "info", "action": "query", "msgid": msg_id, "timestamp": now_ms()}
        with MqttClient(self.creds) as client:
            client.subscribe(self.report_topic())
            client.publish(self.command_topic("slicer", "info"), payload)
            messages = client.read_publishes(10)
        report = None
        for message in messages:
            topic = message["topic"]
            body = message["payload"]
            if topic.endswith("/info/report") and isinstance(body, dict):
                report = body
        return {"report": report, "messages": messages, "info": self.safe_info()}

    def control(self, action, data):
        payload = {"type": action["type"], "action": action["action"], "timestamp": now_ms(), "msgid": str(uuid.uuid4())}
        if data is not None:
            payload["data"] = data
        self.publish(action.get("source", "web"), action["kind"], payload)
        return {"ok": True, "payload": payload}

    def upload(self, content_type, body, start_print=False):
        upload_url = self.info.get("fileUploadurl")
        if not upload_url:
            upload_url = self.fetch_info()["fileUploadurl"]
        request = urllib.request.Request(upload_url, data=body, method="POST")
        request.add_header("Content-Type", content_type)
        request.add_header("X-File-Length", str(len(body)))
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                reply = response.read().decode("utf-8", "replace")
                code = response.status
        except urllib.error.HTTPError as exc:
            reply = exc.read().decode("utf-8", "replace")
            code = exc.code
        filename = "upload.gcode"
        match = re.search(rb'filename="([^"]+)"', body[:4096])
        if match:
            filename = os.path.basename(match.group(1).decode("utf-8", "replace"))
        if start_print and code < 400:
            self.start_print(filename)
        return {"status": code, "reply": reply, "filename": filename}

    def start_print(self, filename):
        data = {"taskid": str(random.randint(1, 1000000)), "filename": filename, "filetype": 1}
        return self.control({"source": "slicer", "kind": "print", "type": "print", "action": "start"}, data)


PRINTER = None


def json_response(handler, obj, status=200):
    body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler, body, content_type="text/html; charset=utf-8"):
    data = body.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self):
        try:
            if self.path == "/" or self.path.startswith("/?"):
                text_response(self, HTML)
            elif self.path == "/api/info":
                json_response(self, PRINTER.safe_info())
            elif self.path == "/api/status":
                json_response(self, PRINTER.status())
            elif self.path == "/api/refresh":
                json_response(self, PRINTER.refresh())
            else:
                self.send_error(404)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            if self.path == "/api/upload":
                start_print = "start=1" in (self.headers.get("X-Panel-Options", ""))
                json_response(self, PRINTER.upload(self.headers.get("Content-Type", ""), body, start_print))
                return
            payload = json.loads(body.decode("utf-8") or "{}")
            action = payload.get("action")
            if self.path == "/api/control":
                json_response(self, self.handle_control(action, payload))
            else:
                self.send_error(404)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)

    def handle_control(self, action, payload):
        value = payload.get("value")
        if action == "video":
            return PRINTER.control({"source": "web", "kind": "video", "type": "video", "action": "startCapture"}, None)
        if action == "light":
            return PRINTER.control(
                {"source": "web", "kind": "light", "type": "light", "action": "control"},
                {"type": int(payload.get("lightType", 3)), "status": int(value), "brightness": 100 if int(value) else 0},
            )
        if action == "temp":
            settings = {payload["field"]: int(value)}
            return PRINTER.control(
                {"source": "web", "kind": "print", "type": "print", "action": "update"},
                {"taskid": str(payload.get("taskid") or "-1"), "settings": settings},
            )
        if action == "speed":
            return PRINTER.control(
                {"source": "web", "kind": "print", "type": "print", "action": "update"},
                {"taskid": "-1", "settings": {"print_speed_mode": int(value)}},
            )
        if action == "fan":
            return PRINTER.control(
                {"source": "web", "kind": "print", "type": "print", "action": "update"},
                {"taskid": "-1", "settings": {payload["field"]: int(value)}},
            )
        if action == "start":
            return PRINTER.start_print(str(payload["filename"]))
        if action == "stop":
            return PRINTER.control(
                {"source": "web", "kind": "print", "type": "print", "action": "stop"},
                {"taskid": str(payload.get("taskid") or "-1")},
            )
        raise ValueError(f"unknown action: {action}")


HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kobra S1 Max Panel</title>
  <style>
    :root { color-scheme: light; --ink:#151515; --muted:#6b6f76; --line:#d8dde3; --panel:#f7f8fa; --accent:#0b6bcb; --ok:#167247; --warn:#9a5b00; --bad:#b42318; }
    * { box-sizing: border-box; }
    body { margin:0; font:14px/1.45 system-ui, -apple-system, Segoe UI, sans-serif; color:var(--ink); background:#fff; }
    header { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:16px 20px; border-bottom:1px solid var(--line); background:#fff; position:sticky; top:0; z-index:2; }
    h1 { font-size:18px; margin:0; font-weight:650; }
    main { max-width:1180px; margin:0 auto; padding:18px; display:grid; gap:16px; }
    section { border-top:1px solid var(--line); padding-top:16px; }
    h2 { margin:0 0 10px; font-size:15px; }
    .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }
    .card { border:1px solid var(--line); border-radius:8px; padding:12px; background:var(--panel); min-height:86px; }
    .label { color:var(--muted); font-size:12px; }
    .value { font-size:26px; font-weight:700; margin-top:2px; }
    .row { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
    button, input, select { font:inherit; }
    button { border:1px solid #aab2bd; background:#fff; border-radius:7px; padding:8px 10px; cursor:pointer; min-height:38px; }
    button.primary { background:var(--accent); color:#fff; border-color:var(--accent); }
    button.danger { color:#fff; background:var(--bad); border-color:var(--bad); }
    input[type=number], input[type=text] { width:110px; border:1px solid #aab2bd; border-radius:7px; padding:8px; min-height:38px; }
    input[type=file] { max-width:100%; }
    .wide { grid-column:1 / -1; }
    .pill { display:inline-flex; align-items:center; min-height:28px; padding:4px 9px; border-radius:999px; border:1px solid var(--line); background:#fff; color:var(--muted); }
    .ok { color:var(--ok); } .warn { color:var(--warn); } .bad { color:var(--bad); }
    pre { white-space:pre-wrap; word-break:break-word; background:#0f1720; color:#dbe7ff; padding:12px; border-radius:8px; max-height:260px; overflow:auto; }
    .toolbar { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
    .split { display:grid; grid-template-columns:1.2fr .8fr; gap:16px; }
    @media (max-width: 760px) { header { align-items:flex-start; flex-direction:column; } .split { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Anycubic Kobra S1 Max</h1>
      <div class="row"><span class="pill" id="cn">CN</span><span class="pill" id="device">Device</span><span class="pill" id="firmware">Firmware</span></div>
    </div>
    <div class="toolbar">
      <button onclick="refreshCreds()">Refresh Link</button>
      <button class="primary" onclick="loadStatus()">Refresh Status</button>
    </div>
  </header>
  <main>
    <section>
      <div class="grid">
        <div class="card"><div class="label">State</div><div class="value" id="state">...</div></div>
        <div class="card"><div class="label">Nozzle</div><div class="value"><span id="nozzle">--</span> C</div></div>
        <div class="card"><div class="label">Bed</div><div class="value"><span id="bed">--</span> C</div></div>
        <div class="card"><div class="label">Chamber</div><div class="value"><span id="chamber">--</span> C</div></div>
      </div>
    </section>
    <div class="split">
      <section>
        <h2>Controls</h2>
        <div class="grid">
          <div class="card">
            <div class="label">Temperatures</div>
            <div class="row"><input id="targetNozzle" type="number" min="0" max="320" value="0"><button onclick="setTemp('target_nozzle_temp','targetNozzle')">Set Nozzle</button></div>
            <div class="row"><input id="targetBed" type="number" min="0" max="120" value="0"><button onclick="setTemp('target_hotbed_temp','targetBed')">Set Bed</button></div>
            <div class="row"><input id="targetChamber" type="number" min="0" max="80" value="0"><button onclick="setTemp('target_chamber_temp','targetChamber')">Set Chamber</button></div>
          </div>
          <div class="card">
            <div class="label">Airflow</div>
            <div class="row"><input id="fan" type="number" min="0" max="100" value="0"><button onclick="setFan('fan_speed_pct','fan')">Part Fan</button></div>
            <div class="row"><input id="auxFan" type="number" min="0" max="100" value="0"><button onclick="setFan('aux_fan_speed_pct','auxFan')">Aux Fan</button></div>
            <div class="row"><input id="boxFan" type="number" min="0" max="100" value="0"><button onclick="setFan('box_fan_level','boxFan')">Box Fan</button></div>
          </div>
          <div class="card">
            <div class="label">Lights</div>
            <div class="row"><button onclick="light(3,1)">Chamber On</button><button onclick="light(3,0)">Chamber Off</button></div>
            <div class="row"><button onclick="light(1,1)">Head On</button><button onclick="light(1,0)">Head Off</button></div>
          </div>
          <div class="card">
            <div class="label">Motion Profile</div>
            <div class="row"><button onclick="speed(1)">Quiet</button><button onclick="speed(2)">Standard</button><button onclick="speed(3)">Sport</button></div>
          </div>
          <div class="card">
            <div class="label">Camera</div>
            <div class="row"><button onclick="video()">Start Stream</button><a id="cameraLink" target="_blank"><button>Open FLV</button></a></div>
          </div>
          <div class="card">
            <div class="label">Print</div>
            <div class="row"><input id="startName" type="text" placeholder="file.gcode"><button onclick="startPrint()">Start</button><button class="danger" onclick="stopPrint()">Stop</button></div>
          </div>
        </div>
      </section>
      <section>
        <h2>Upload</h2>
        <div class="card">
          <form id="uploadForm">
            <div class="row"><input name="file" type="file" accept=".gcode,.3mf,.zip"></div>
            <div class="row"><button class="primary">Upload</button><label><input id="autoStart" type="checkbox"> start after upload</label></div>
          </form>
        </div>
        <h2>Events</h2>
        <pre id="log"></pre>
      </section>
    </div>
  </main>
<script>
const log = (m) => { const el=document.getElementById('log'); el.textContent = `[${new Date().toLocaleTimeString()}] ${m}\n` + el.textContent; };
async function api(path, opts={}) {
  const r = await fetch(path, opts);
  const j = await r.json();
  if (!r.ok || j.error) throw new Error(j.error || r.statusText);
  return j;
}
function applyInfo(info) {
  const p = info.printer || {};
  const c = info.ctrl || {};
  document.getElementById('cn').textContent = p.cn || 'CN';
  document.getElementById('device').textContent = c.deviceId || p.usn || 'Device';
  document.getElementById('firmware').textContent = p.modelName || 'Firmware';
  document.getElementById('cameraLink').href = p.rtspUrl || `http://${location.hostname}:18088/flv`;
}
function applyReport(report) {
  if (!report || !report.data) return;
  const d = report.data, t = d.temp || {};
  document.getElementById('firmware').textContent = `${d.model || 'Kobra'} ${d.version || ''}`.trim();
  document.getElementById('state').textContent = d.state || '--';
  document.getElementById('nozzle').textContent = t.curr_nozzle_temp ?? '--';
  document.getElementById('bed').textContent = t.curr_hotbed_temp ?? '--';
  document.getElementById('chamber').textContent = t.curr_chamber_temp ?? '--';
  document.getElementById('targetNozzle').value = t.target_nozzle_temp ?? 0;
  document.getElementById('targetBed').value = t.target_hotbed_temp ?? 0;
  document.getElementById('targetChamber').value = t.target_chamber_temp ?? 0;
  document.getElementById('fan').value = d.fan_speed_pct ?? 0;
  document.getElementById('auxFan').value = d.aux_fan_speed_pct ?? 0;
  document.getElementById('boxFan').value = d.box_fan_level ?? 0;
}
async function loadInfo() { const j = await api('/api/info'); applyInfo(j); }
async function refreshCreds() { const j = await api('/api/refresh'); applyInfo(j); log('link refreshed'); }
async function loadStatus() {
  const j = await api('/api/status'); applyInfo(j.info); applyReport(j.report); log(j.report ? 'status updated' : 'no status report received');
}
async function control(body) {
  const j = await api('/api/control', {method:'POST', body:JSON.stringify(body)});
  log(`${body.action}: sent`);
  return j;
}
const setTemp = (field,id) => control({action:'temp', field, value:document.getElementById(id).value});
const setFan = (field,id) => control({action:'fan', field, value:document.getElementById(id).value});
const speed = (value) => control({action:'speed', value});
const light = (lightType,value) => control({action:'light', lightType, value});
const video = () => control({action:'video'});
const stopPrint = () => control({action:'stop'});
const startPrint = () => control({action:'start', filename:document.getElementById('startName').value});
document.getElementById('uploadForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const headers = {};
  if (document.getElementById('autoStart').checked) headers['X-Panel-Options'] = 'start=1';
  const j = await api('/api/upload', {method:'POST', headers, body:new FormData(e.target)});
  document.getElementById('startName').value = j.filename || '';
  log(`upload ${j.status}: ${j.filename}`);
});
loadInfo().then(loadStatus).catch(err => log(err.message));
setInterval(() => loadStatus().catch(err => log(err.message)), 15000);
</script>
</body>
</html>
'''


def main():
    global PRINTER
    PRINTER = Printer()
    server = ThreadingHTTPServer((PANEL_HOST, PANEL_PORT), Handler)
    print(f"Anycubic panel: http://{PANEL_HOST}:{PANEL_PORT}")
    print(f"Printer: {PRINTER.info.get('modelName')} {PRINTER.info.get('cn')} at {PRINTER.info.get('ip')}")
    server.serve_forever()


if __name__ == "__main__":
    main()
