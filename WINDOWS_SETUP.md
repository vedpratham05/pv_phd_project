# Windows Setup Guide — Campus eKYC & Security Console

Full setup for running the project on a Windows 10/11 PC.

---

## 1. Install Python 3.11 (64-bit) — IMPORTANT: not 3.13

The pinned dependencies (`numpy 1.26.4`, `dlib-bin`, `ultralytics 8.2.60`) ship
pre-built wheels for Python **3.10–3.12** only. Python 3.13 will fail to install.

1. Download **Python 3.11.x (64-bit)** from https://www.python.org/downloads/windows/
2. In the installer, tick **"Add python.exe to PATH"**.
3. Verify in a new Command Prompt / PowerShell:
   ```powershell
   py -3.11 --version
   ```

## 2. Copy the project folder

Copy the whole `pranali_mam_phd_pj` folder to the Windows PC (e.g. `C:\Projects\pranali_mam_phd_pj`).

Include these files if you want to keep existing data:
- `fastapi_backend\visitor_system.db` and `fastapi_backend\college_system.db` (all visitors, faculty, cameras, alerts)
- `sbox_live_key.csv` / `sbox_test_key.csv` (Aadhaar sandbox API keys)
- `fastapi_backend\yolov8n.pt` (YOLOv8 weights — avoids re-download on first run)

## 3. Create ONE virtual environment and install everything

Open PowerShell in the project root:

```powershell
cd C:\Projects\pranali_mam_phd_pj

py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r fastapi_backend\requirements.txt
pip install -r requirements.txt
```

> If PowerShell blocks activation ("running scripts is disabled"), run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` and retry.
>
> Use ONE venv for both servers — the backend auto-launches `edge_bridge.py`
> with the same Python it runs under, so the bridge needs `opencv` + `requests`
> available in that same environment.

## 4. Run the backend (FastAPI, port 8000)

In the activated venv:

```powershell
cd fastapi_backend
uvicorn main:app --reload
```

- API docs: http://127.0.0.1:8000/docs
- On startup it seeds the camera registry, starts the **camera auto-heal loop**
  (finds IP-Webcam phones on the WiFi every ~20 s), and **auto-launches
  `edge_bridge.py`** — you do NOT run the bridge manually.

## 5. Run the frontend (Flask, port 5000)

Open a **second** PowerShell window:

```powershell
cd C:\Projects\pranali_mam_phd_pj
.\venv\Scripts\Activate.ps1
python app.py
```

- Open the console: http://127.0.0.1:5000

## 6. Phone cameras (IP Webcam)

1. Install **IP Webcam** (Pavel Khlebovich) on each Android phone.
2. Connect every phone to the **same WiFi network as the PC**.
3. In IP Webcam: scroll down → **Start server** (default port 8080).
4. That's it — the backend scans the LAN and assigns phones to camera nodes
   automatically (entrance/floor cameras first). No IP typing needed.
   You can also use the **"Auto-Detect Cameras on WiFi"** button on the admin
   dashboard, or assign an IP manually per camera node.

## 7. Windows Firewall

The first time Python runs, Windows shows a firewall prompt — click **Allow**
for **Private networks**. This is required for:
- the LAN scan that auto-discovers the phones, and
- pulling the MJPEG video streams from the phones.

If you skipped the prompt: Windows Security → Firewall & network protection →
Allow an app through firewall → allow `python.exe` on Private.

## 8. Optional: Twilio SMS

SMS alerts are printed to the backend console by default (placeholder
credentials). To send real SMS, edit the credentials at the top of
`fastapi_backend\app\api\workflow.py` (`TWILIO_SID` / `TWILIO_TOKEN` /
`TWILIO_SMS_FROM`). Never commit real credentials to a public repo.

## Quick daily start (after setup)

```powershell
# Terminal 1
cd C:\Projects\pranali_mam_phd_pj
.\venv\Scripts\Activate.ps1
cd fastapi_backend
uvicorn main:app --reload

# Terminal 2
cd C:\Projects\pranali_mam_phd_pj
.\venv\Scripts\Activate.ps1
python app.py
```

Then start IP Webcam on the phones and open http://127.0.0.1:5000.

## Troubleshooting

| Problem | Fix |
|---|---|
| `pip install` fails building numpy/dlib | You're on Python 3.13 — recreate the venv with `py -3.11 -m venv venv`. |
| Camera never detected | Phone and PC must be on the same WiFi; IP Webcam server started; firewall allowed on Private networks. Phone hotspot mode also works (connect the PC to the phone's hotspot). |
| `Surveillance Stream Offline` on dashboard | Normal when no phone is live — it auto-connects within ~20 s of the phone's camera server starting. |
| Port already in use | Something else is on 8000/5000 — stop it or change the port (`uvicorn main:app --port 8001`, and update `API_BASE_URL` in `static/app.js`). |
| First run is slow | ultralytics may download YOLO weights and warm up — subsequent runs are fast. |
