# Anycubic Kobra S1 Max LAN Panel

`anycubic_panel.py` is a local browser panel for an Anycubic Kobra S1 Max / KS1M that is already on Wi-Fi, but cannot be operated from the touchscreen or bound in the Anycubic app.

It talks to the printer over the same LAN services used by the app:

- `GET http://<printer-ip>:18910/info` to discover the printer CN, upload URL, camera URL, and LAN token.
- `POST http://<printer-ip>:18910/ctrl` to retrieve the local MQTT credentials.
- TLS MQTT on `<printer-ip>:9883` for status and control commands.
- `POST http://<printer-ip>:18910/gcode_upload?s=...` for file upload.

The script runs only on your computer. It does not install anything on the printer.

## Requirements

- Windows with PowerShell 7 or Windows PowerShell available as `pwsh` or `powershell`
- Python 3.10 or newer
- The printer and computer on the same LAN
- The printer already connected to Wi-Fi

No Python packages are required.

## Quick Start

From this folder:

```powershell
python .\anycubic_panel.py
```

Then open:

```text
http://127.0.0.1:8765
```

If your printer uses a different IP:

```powershell
$env:ANYCUBIC_IP = "192.168.1.144"
python .\anycubic_panel.py
```

Optional environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANYCUBIC_IP` | `192.168.1.144` | Printer IP address |
| `ANYCUBIC_MODEL_ID` | `20029` | Kobra S1 Max model id |
| `PANEL_HOST` | `127.0.0.1` | Local web server bind address |
| `PANEL_PORT` | `8765` | Local web server port |

## What The Panel Can Do

- Query printer status
- Show current and target temperatures
- Set nozzle, bed, and chamber target temperatures
- Set fan values and print speed mode
- Toggle chamber/head lights
- Start the camera stream command and link to the FLV stream
- Upload G-code / 3MF / ZIP files through the printer upload endpoint
- Start or stop print jobs through MQTT

Use heating and print commands with the same care you would use on the touchscreen. The panel sends real printer commands.

## How To Extract The CN Code

The CN code is exposed by the printer's LAN info endpoint after the printer joins Wi-Fi.

Replace the IP address with your printer's IP:

```powershell
Invoke-RestMethod -Uri "http://192.168.1.144:18910/info" | Select-Object cn
```

Example output:

```text
cn
--
1234-5678-9ABC-DEF0
```

You can also view the full discovery response:

```powershell
Invoke-RestMethod -Uri "http://192.168.1.144:18910/info" | ConvertTo-Json -Depth 5
```

Useful fields include:

| Field | Meaning |
| --- | --- |
| `cn` | The binding code shown in the printer QR code |
| `modelId` | Kobra S1 Max is `20029` |
| `ctrlInfoUrl` | LAN `/ctrl` endpoint |
| `fileUploadurl` | Printer upload endpoint |
| `rtspUrl` | Camera stream URL, usually `http://<ip>:18088/flv` |
| `token` | LAN token used to sign `/ctrl` requests |

## QR Code Format For Binding

The binding QR code can be generated from the raw CN string.

For example, if the CN is:

```text
1234-5678-9ABC-DEF0
```

The QR payload should be exactly:

```text
1234-5678-9ABC-DEF0
```

Do not wrap it in JSON and do not prefix it with `CN=`.

Any QR generator can be used as long as it encodes the raw CN text and leaves a normal quiet zone around the QR code.

## How The `/ctrl` Request Is Signed

The printer's `/ctrl` endpoint requires four query parameters:

- `ts`: current Unix timestamp in milliseconds
- `nonce`: any non-empty random string
- `did`: any non-empty device id value; the CN works
- `sign`: MD5 signature

Signature formula:

```text
inner = md5(first_16_chars_of_info_token)
sign  = md5(inner + ts + nonce)
```

The `/ctrl` response contains encrypted LAN MQTT credentials. The response is decrypted with AES-CBC:

- AES key: last 16 characters of the `/info` token
- AES IV: `data.token` from the `/ctrl` response
- ciphertext: base64-decoded `data.info` from the `/ctrl` response

The panel performs this automatically at startup.

## Notes And Safety

- The MQTT client certificate/private key returned by `/ctrl` is written only to a temporary directory for the running process.
- The panel API redacts the raw `/info` token and upload secret before returning discovery data to the browser.
- Keep the panel bound to `127.0.0.1` unless you intentionally want another computer on your LAN to access it.
- If the printer IP changes, rerun the script with `ANYCUBIC_IP` set to the new address.

## Troubleshooting

If the panel starts but status does not update:

1. Confirm the printer is reachable:

   ```powershell
   Invoke-RestMethod -Uri "http://192.168.1.144:18910/info"
   ```

2. Confirm TLS MQTT is open:

   ```powershell
   Test-NetConnection 192.168.1.144 -Port 9883
   ```

3. Restart the panel after changing `ANYCUBIC_IP`.

If the CN command fails, the printer is probably not on Wi-Fi yet, the IP address is wrong, or the printer is still booting.
