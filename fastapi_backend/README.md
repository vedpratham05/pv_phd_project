# AI Smart Visitor Backend (FastAPI)

This backend implements the next module after Aadhaar OTP verification:

- DigiLocker consent-based Aadhaar profile upsert (`aadhaar_master`)
- Face registration + liveness checks (`face_embeddings`)
- Face-vs-Aadhaar matching
- Visitor profile and pass generation (`visitor_master`, `visit_sessions`, `qr_passes`)
- Returning visitor check-in by face match
- Verification event audit (`verification_logs`)

## Database Tables

- `aadhaar_master`
- `visitor_master`
- `face_embeddings`
- `visit_sessions`
- `qr_passes`
- `verification_logs`

## Run

From the project root:

```bash
cd fastapi_backend
python3 -m pip install -r requirements.txt
uvicorn main:app --reload
```

Open API docs:

- `http://127.0.0.1:8000/docs`

## Important Notes

- Current face embedding implementation is deterministic fallback logic to keep the workflow runnable. Replace `app/services/face_service.py` with ArcFace/FaceNet in production.
- Webcam auto-open must be implemented in frontend JS (browser permission flow). Backend provides the workflow APIs.
- Direct Sandbox Aadhaar OKYC OTP endpoints are discontinued. The workflow now
  initiates a DigiLocker session, opens the returned authorization URL, polls
  session status, and retrieves the consented user profile.
- Set `DIGILOCKER_REDIRECT_URL` in `.env` to an HTTPS, publicly accessible URL.
  For local development, the default Sandbox documentation URL is accepted by
  the API, while the local page continues polling the session.
- Configure Twilio notifications through environment variables
  (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, and
  `TWILIO_SMS_FROM`). Never commit these credentials to source control.


environment 

source ./env/bin/activate

backend run 
(env) prathamved@MacBook-Air fastapi_backend % uvicorn main:app --reload

frontend run 

(env) prathamved@MacBook-Air pranali mam phd pj % python3 app.py



# 1. Clean out the broken installation caches
pip cache purge

# 2. Re-install the correct pre-built dlib binary package for Apple Silicon Mac
pip install --force-reinstall dlib-bin==20.0.1

# 3. Install face_recognition WITHOUT allowing it to overwrite or re-compile dlib
pip install face_recognition --no-dependencies

# 4. Restart your application server
python3 -m uvicorn main:app --reload