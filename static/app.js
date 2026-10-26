const statusPill = document.getElementById('statusPill');
const messageBox = document.getElementById('messageBox');
const sendOtpBtn = document.getElementById('sendOtpBtn');
const verifyBtn = document.getElementById('verifyBtn');
const aadhaarForm = document.getElementById('aadhaarForm');
const otpRow = document.getElementById('otpRow');
const resultCard = document.getElementById('resultCard');
const aadhaarNumberInput = document.getElementById('aadhaarNumber');
const phoneNumberInput = document.getElementById('phoneNumber');
const otpInput = document.getElementById('otpInput');

const profileName = document.getElementById('profileName');
const profileStatus = document.getElementById('profileStatus');
const profileMessage = document.getElementById('profileMessage');
const photoPreview = document.getElementById('photoPreview');
const referenceId = document.getElementById('referenceId');
const phoneDisplay = document.getElementById('phoneDisplay');
const genderDisplay = document.getElementById('genderDisplay');
const dobDisplay = document.getElementById('dobDisplay');
const yobDisplay = document.getElementById('yobDisplay');
const careOfDisplay = document.getElementById('careOfDisplay');
const fullAddressDisplay = document.getElementById('fullAddressDisplay');
const mobileHashDisplay = document.getElementById('mobileHashDisplay');
const emailHashDisplay = document.getElementById('emailHashDisplay');
const shareCodeDisplay = document.getElementById('shareCodeDisplay');
const addressDisplay = document.getElementById('addressDisplay');

const startCaptureBtn = document.getElementById('startCaptureBtn');
// Face Registration & Verification Elements
const faceRegistrationCard = document.getElementById('faceRegistrationCard');
const faceCardTitle = document.getElementById('faceCardTitle') || document.querySelector('#faceRegistrationCard h2');
const videoPreview = document.getElementById('videoPreview');
const registrationControls = document.getElementById('registrationControls');
const revisitControls = document.getElementById('revisitControls');
const authenticateFaceBtn = document.getElementById('authenticateFaceBtn');

const captureFrontBtn = document.getElementById('captureFrontBtn');
const captureLeftBtn = document.getElementById('captureLeftBtn');
const captureRightBtn = document.getElementById('captureRightBtn');
const registerFaceBtn = document.getElementById('registerFaceBtn');
const retryCaptureBtn = document.getElementById('retryCaptureBtn');
const faceGuide = document.querySelector('.face-guide');
const faceMessage = document.getElementById('faceMessage');

let capturedImages = { front: null, left: null, right: null };
let isRevisitMode = false;

// Digital Visitor Form Elements
const visitorFormCard = document.getElementById('visitorFormCard');
const formFullName = document.getElementById('formFullName');
const formDob = document.getElementById('formDob');
const formMobileNumber = document.getElementById('formMobileNumber');
const formEmail = document.getElementById('formEmail');
const formPurpose = document.getElementById('formPurpose');
const formDepartment = document.getElementById('formDepartment');
const formEmployee = document.getElementById('formEmployee');
const formDuration = document.getElementById('formDuration');
const formVehicle = document.getElementById('formVehicle');
const formGracePeriod = document.getElementById('formGracePeriod');
const formMeetingFloor = document.getElementById('formMeetingFloor');
const submitVisitorFormBtn = document.getElementById('submitVisitorFormBtn');

let flowId = '';
const API_BASE_URL = window.VISITOR_API_BASE_URL || 'http://127.0.0.1:8000';
let latestAadhaarPayload = null;

// Dual Dashboard Selection Nodes
const toggleVisitorViewBtn = document.getElementById('toggleVisitorViewBtn');
const toggleAdminViewBtn = document.getElementById('toggleAdminViewBtn');
const visitorWorkspaceView = document.getElementById('visitorWorkspaceView');
const adminWorkspaceView = document.getElementById('adminWorkspaceView');

// Injected Live IP Camera Controls Selectors
const syncCamIpBtn = document.getElementById('syncCamIpBtn');
const dynamicCamIpInput = document.getElementById('dynamicCamIpInput');
const adminLiveFeedFrame = document.getElementById('adminLiveFeedFrame');
const streamStatusIndicator = document.getElementById('streamStatusIndicator');
const camFeedOffline = document.getElementById('camFeedOffline');

// Show the entrance <img> feed only when it actually has a reachable stream;
// otherwise show the clean offline placeholder instead of a broken image icon.
function showEntranceOffline(message) {
  if (adminLiveFeedFrame) {
    adminLiveFeedFrame.classList.add('hidden');
    adminLiveFeedFrame.removeAttribute('src');
  }
  if (camFeedOffline) camFeedOffline.classList.remove('hidden');
  if (streamStatusIndicator) {
    streamStatusIndicator.textContent = message || '⚪ CAMERA OFFLINE';
    streamStatusIndicator.style.color = '#f59e0b';
  }
}

function showEntranceOnline(streamUrl) {
  if (!adminLiveFeedFrame) return;
  if (adminLiveFeedFrame.src !== streamUrl) adminLiveFeedFrame.src = streamUrl;
  adminLiveFeedFrame.classList.remove('hidden');
  if (camFeedOffline) camFeedOffline.classList.add('hidden');
  if (streamStatusIndicator) {
    streamStatusIndicator.textContent = '🟢 LIVE — AUTO-DETECTED';
    streamStatusIndicator.style.color = '#10b981';
  }
}

// A broken/unreachable stream fires the <img> onerror — fall back to offline.
if (adminLiveFeedFrame) {
  adminLiveFeedFrame.addEventListener('error', () => showEntranceOffline('⚪ CAMERA OFFLINE'));
}

// Drives the main entrance feed from the camera registry: whichever entrance
// camera (CAM_FLOOR_0, or the lowest-floor camera) has a stream is shown.
let _entranceStreamUrl = null;
async function refreshEntranceFeed() {
  if (!adminLiveFeedFrame) return;
  try {
    const response = await fetch(`${API_BASE_URL}/workflow/cameras`);
    if (!response.ok) return;
    const cameras = await response.json();
    if (!Array.isArray(cameras)) return;
    const entrance =
      cameras.find((c) => c.camera_id === 'CAM_FLOOR_0' && c.stream_url) ||
      cameras.find((c) => c.stream_url);
    const url = entrance ? entrance.stream_url : null;
    if (url) {
      if (url !== _entranceStreamUrl) {
        _entranceStreamUrl = url;
        showEntranceOnline(url);
      }
    } else {
      _entranceStreamUrl = null;
      showEntranceOffline('⏳ WAITING FOR CAMERA…');
    }
  } catch (err) {
    // keep current state
  }
}

async function apiRequest(path, body) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  const data = await response.json();
  if (!response.ok) {
    throw data;
  }
  return data;
}

function normalizePhotoSource(photo) {
  if (!photo || typeof photo !== 'string') return '';
  const compact = photo.trim().replace(/\s+/g, '');
  if (!compact) return '';
  if (compact.startsWith('data:image/')) return compact;
  if (/^[A-Za-z0-9+/=]+$/.test(compact)) return `data:image/jpeg;base64,${compact}`;
  return compact;
}

function setStatus(text, tone = 'info') {
  statusPill.textContent = text;
  statusPill.style.color = tone === 'error' ? 'var(--danger)' : tone === 'success' ? 'var(--success)' : 'var(--accent)';
}

function setMessage(text, tone = 'info') {
  messageBox.textContent = text;
  messageBox.style.color = tone === 'error' ? 'var(--danger)' : tone === 'success' ? 'var(--success)' : 'var(--muted)';
}

function showResult(profile) {
  resultCard.classList.remove('hidden');
  profileName.textContent = profile.name || 'Profile';
  profileStatus.textContent = profile.status || 'Verified';
  profileMessage.textContent = profile.message || '';
  referenceId.textContent = profile.reference_id || '';
  phoneDisplay.textContent = profile.phone_number || 'Not provided';
  genderDisplay.textContent = profile.gender || '';
  dobDisplay.textContent = profile.date_of_birth || '';
  yobDisplay.textContent = profile.year_of_birth || '';
  careOfDisplay.textContent = profile.care_of || '';
  fullAddressDisplay.textContent = profile.address || '';
  mobileHashDisplay.textContent = profile.mobile_hash || '';
  emailHashDisplay.textContent = profile.email_hash || '';
  shareCodeDisplay.textContent = profile.share_code || '';
  addressDisplay.textContent = profile.address || 'Address not returned by API';

  const photoSource = normalizePhotoSource(profile.aadhaar_photo);
  if (photoSource) {
    photoPreview.src = photoSource;
    photoPreview.alt = `${profile.name} profile photo`;
  } else {
    photoPreview.removeAttribute('src');
    photoPreview.alt = 'Profile photo unavailable';
  }
}

sendOtpBtn.addEventListener('click', async () => {
  const aadhaar_number = aadhaarNumberInput.value.trim();
  const digilockerWindow = window.open('', '_blank');
  setStatus('Processing...');
  resultCard.classList.add('hidden');

  try {
    const data = await apiRequest('/workflow/aadhaar/start', { aadhaar_number });

    if (data.pre_verified && data.aadhaar) {
      isRevisitMode = true;
      setStatus('Returning Visitor', 'success');
      setMessage(data.message, 'success');

      latestAadhaarPayload = { aadhaar: data.aadhaar, raw_response: {} };

      const profile = {
        ...data.aadhaar,
        name: data.aadhaar.full_name,
        phone_number: phoneNumberInput.value.trim() || 'Pre-registered Account',
      };
      showResult(profile);
    } else {
      isRevisitMode = false;
      flowId = data.flow_id;
      if (data.authorization_url) {
        if (digilockerWindow) {
          digilockerWindow.location = data.authorization_url;
        } else {
          window.open(data.authorization_url, '_blank');
        }
      }
      otpRow.classList.remove('hidden');
      otpInput.classList.add('hidden');
      setStatus('OTP Sent', 'success');
      verifyBtn.textContent = 'Verify DigiLocker';
      setMessage('Complete Aadhaar OTP and consent in the DigiLocker window, then click Verify DigiLocker.', 'success');
    }
  } catch (error) {
    if (digilockerWindow) digilockerWindow.close();
    setStatus('Error', 'error');
    setMessage(error.detail || error.error || 'Identity lookup failure.', 'error');
  }
});

verifyBtn.addEventListener('click', async () => {
  setStatus('Verifying OTP...');

  try {
  const data = await apiRequest('/workflow/aadhaar/verify', { flow_id: flowId, otp: '' });
    latestAadhaarPayload = data;

    const profile = {
      ...data.aadhaar,
      name: data.aadhaar.full_name,
      status: 'VALID',
      message: 'Aadhaar details verified successfully.',
    };

    setStatus('Verified', 'success');
    setMessage('Aadhaar profile verification loaded.', 'success');
    showResult(profile);
  } catch (error) {
    setStatus('Verification failed', 'error');
    if (String(error.detail || error.error || '').toLowerCase().includes('expired')) {
      flowId = '';
      otpInput.value = '';
      setMessage('This OTP has expired. Click Send OTP to request a new OTP, then enter only the latest code.', 'error');
    } else {
      setMessage(error.detail || error.error || 'Verification exception.', 'error');
    }
  }
});

async function startFaceRegistration() {
  resultCard.classList.add('hidden');
  faceRegistrationCard.classList.remove('hidden');

  if (isRevisitMode) {
    if (faceCardTitle) faceCardTitle.textContent = "Identity Verification Check";
    faceMessage.textContent = "Gaze into the viewport for instant snapshot validation.";
    faceMessage.style.color = 'var(--muted)';
    if (registrationControls) registrationControls.classList.add('hidden');
    if (revisitControls) revisitControls.classList.remove('hidden');
    registerFaceBtn.classList.add('hidden');
  } else {
    if (faceCardTitle) faceCardTitle.textContent = "New Face Enrollment Registration";
    faceMessage.textContent = "Complete standard three-angle capture sequence.";
    faceMessage.style.color = 'var(--muted)';
    if (registrationControls) registrationControls.classList.remove('hidden');
    if (revisitControls) revisitControls.classList.add('hidden');
    registerFaceBtn.classList.remove('hidden');
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    videoPreview.srcObject = stream;
    videoPreview.play();
  } catch (err) {
    faceMessage.textContent = `Webcam runtime blocked: ${err.message}.`;
    faceMessage.style.color = 'var(--danger)';
    return;
  }
}

function captureFrameBase64() {
  const canvas = document.createElement('canvas');
  canvas.width = videoPreview.videoWidth;
  canvas.height = videoPreview.videoHeight;
  canvas.getContext('2d').drawImage(videoPreview, 0, 0);
  return canvas.toDataURL('image/jpeg').split(',')[1];
}

if (authenticateFaceBtn) {
  authenticateFaceBtn.addEventListener('click', async () => {
    authenticateFaceBtn.disabled = true;
    faceMessage.textContent = "Matching live values against the facial database tracking registries...";
    faceMessage.style.color = 'var(--muted)';
    faceGuide.classList.remove('danger', 'success');

    const oldFallbackBtn = document.getElementById('fallbackEnrollBtn');
    if (oldFallbackBtn) oldFallbackBtn.remove();

    try {
      const liveSnapshotFrame = captureFrameBase64();
      const targetAadhaarId = latestAadhaarPayload.aadhaar.id || latestAadhaarPayload.aadhaar.aadhaar_id;
      
      if (!targetAadhaarId) {
        throw new Error("Aadhaar identifier index key missing from session.");
      }

      const verificationPayload = {
        aadhaar_id: parseInt(targetAadhaarId, 10),
        front_image_base64: liveSnapshotFrame,
        blink_done: true,
        is_revisit: true 
      };

      const data = await apiRequest('/workflow/face/register', verificationPayload);

      faceMessage.textContent = `Authentication Confirmed! ${data.status}`;
      faceMessage.style.color = 'var(--success)';
      faceGuide.classList.add('success');

      setTimeout(() => {
        if (videoPreview.srcObject) {
          videoPreview.srcObject.getTracks().forEach((track) => track.stop());
        }
        showVisitorForm(data.visitor_id, data.auto_filled_profile);
      }, 1100);

    } catch (error) {
      let displayError = error.message || 'Validation Failure';
      if (typeof error === 'object' && error.detail) {
        displayError = Array.isArray(error.detail) ? error.detail.map(err => `${err.loc ? err.loc.join('.') : 'Field'}: ${err.msg}`).join(' | ') : error.detail;
      }
      faceMessage.textContent = `Authentication Refused: ${displayError}`;
      faceMessage.style.color = 'var(--danger)';
      faceGuide.classList.add('danger');
      authenticateFaceBtn.disabled = false;

      const fallbackBtn = document.createElement('button');
      fallbackBtn.id = 'fallbackEnrollBtn';
      fallbackBtn.textContent = '📸 Profile Not Found: Register as New Face';
      fallbackBtn.style.marginTop = '15px';
      fallbackBtn.style.width = '100%';
      fallbackBtn.style.padding = '14px';
      fallbackBtn.style.background = 'linear-gradient(135deg, var(--accent), #1d4ed8)';
      fallbackBtn.style.color = '#ffffff';
      fallbackBtn.style.fontWeight = 'bold';
      fallbackBtn.style.borderRadius = '6px';
      fallbackBtn.style.border = 'none';
      fallbackBtn.style.cursor = 'pointer';

      fallbackBtn.addEventListener('click', () => {
        isRevisitMode = false;
        fallbackBtn.remove();
        faceGuide.classList.remove('success', 'danger');

        if (registrationControls) registrationControls.classList.remove('hidden');
        if (revisitControls) revisitControls.classList.add('hidden');
        if (registerFaceBtn) {
          registerFaceBtn.classList.remove('hidden');
          registerFaceBtn.disabled = true;
        }

        if (faceCardTitle) faceCardTitle.textContent = "New Face Enrollment Registration";
        faceMessage.textContent = "Please capture all three angles (Front, Left, Right) to construct your biometric credentials profile.";
        faceMessage.style.color = 'var(--muted)';

        capturedImages = { front: null, left: null, right: null };
        captureFrontBtn.disabled = false;
        captureFrontBtn.textContent = 'Capture Front';
        captureLeftBtn.disabled = false;
        captureLeftBtn.textContent = 'Capture Left';
        captureRightBtn.disabled = false;
        captureRightBtn.textContent = 'Capture Right';
        retryCaptureBtn.classList.add('hidden');

        if (!videoPreview.srcObject || !videoPreview.srcObject.active) {
          startFaceRegistration();
        }
      });

      revisitControls.appendChild(fallbackBtn);
    }
  });
}
// YAHAN PAR PASTE KAREIN
async function loadFacultyData() {
    const response = await fetch(`${API_BASE_URL}/workflow/faculty/list`);
    const faculties = await response.json();
    
    const deptSelect = document.getElementById('formDepartment');
    const empSelect = document.getElementById('formEmployee');

    function updateMeetingFloor() {
        const selected = empSelect.selectedOptions[0];
        const floor = selected ? selected.dataset.floor : null;
        if (formMeetingFloor) {
            formMeetingFloor.textContent = floor != null && floor !== '' ? `Floor ${floor}` : '—';
        }
    }
    
    // Departments fill karein
    const depts = [...new Set(faculties.map(f => f.department))];
    deptSelect.innerHTML = depts.map(d => `<option value="${d}">${d}</option>`).join('');
    
    // Person to Meet filter logic
    deptSelect.onchange = () => {
        empSelect.innerHTML = '';
        faculties.filter(f => f.department === deptSelect.value).forEach(f => {
            empSelect.innerHTML += `<option value="${f.name}" data-floor="${f.floor}">${f.name}</option>`;
        });
        updateMeetingFloor();
    };
    empSelect.onchange = updateMeetingFloor;
    deptSelect.onchange(); // Initial load
}

// Function ko initialize karein taaki page load par dropdown bhar jaye
document.addEventListener('DOMContentLoaded', loadFacultyData);

captureFrontBtn.addEventListener('click', () => {
  capturedImages.front = captureFrameBase64();
  captureFrontBtn.textContent = 'Front ✓';
  captureFrontBtn.disabled = true;
  checkAllCaptured();
});

captureLeftBtn.addEventListener('click', () => {
  capturedImages.left = captureFrameBase64();
  captureLeftBtn.textContent = 'Left ✓';
  captureLeftBtn.disabled = true;
  checkAllCaptured();
});

captureRightBtn.addEventListener('click', () => {
  capturedImages.right = captureFrameBase64();
  captureRightBtn.textContent = 'Right ✓';
  captureRightBtn.disabled = true;
  checkAllCaptured();
});

function checkAllCaptured() {
  if (capturedImages.front && capturedImages.left && capturedImages.right) {
    registerFaceBtn.disabled = false;
    faceMessage.textContent = 'Facial profiles captured. Ready to submit registration data.';
  }
}

registerFaceBtn.addEventListener('click', async () => {
  registerFaceBtn.disabled = true;
  try {
    const targetAadhaarId = latestAadhaarPayload.aadhaar.id || latestAadhaarPayload.aadhaar.aadhaar_id;

    const registrationPayload = {
      aadhaar_id: parseInt(targetAadhaarId, 10),
      front_image_base64: capturedImages.front,
      left_image_base64: capturedImages.left,
      right_image_base64: capturedImages.right,
      blink_done: true,
      turn_left_done: true,
      turn_right_done: true,
      is_revisit: false
    };

    const data = await apiRequest('/workflow/face/register', registrationPayload);
    if (videoPreview.srcObject) {
      videoPreview.srcObject.getTracks().forEach((track) => track.stop());
    }
    showVisitorForm(data.visitor_id, null);
  } catch (error) {
    let displayError = error.message || 'Error occurred';
    if (typeof error === 'object' && error.detail) {
      displayError = Array.isArray(error.detail) ? JSON.stringify(error.detail) : error.detail;
    }
    faceMessage.textContent = displayError;
    retryCaptureBtn.classList.remove('hidden');
  }
});

startCaptureBtn.addEventListener('click', startFaceRegistration);

function resetFaceCapture() {
  capturedImages = { front: null, left: null, right: null };
  if (!videoPreview.srcObject || !videoPreview.srcObject.active) {
    startFaceRegistration();
  }
  captureFrontBtn.disabled = false;
  captureFrontBtn.textContent = 'Capture Front';
  captureLeftBtn.disabled = false;
  captureLeftBtn.textContent = 'Capture Left';
  captureRightBtn.disabled = false;
  captureRightBtn.textContent = 'Capture Right';
  registerFaceBtn.disabled = true;
  if (authenticateFaceBtn) authenticateFaceBtn.disabled = false;
  retryCaptureBtn.classList.add('hidden');
  faceMessage.style.color = 'var(--muted)';
  faceGuide.classList.remove('success', 'danger');
}

retryCaptureBtn.addEventListener('click', resetFaceCapture);

function showVisitorForm(visitorId, autoFilledProfile) {
  aadhaarForm.classList.add('hidden');
  faceRegistrationCard.classList.add('hidden');
  visitorFormCard.classList.remove('hidden');

  if (formGracePeriod && !formGracePeriod.value) {
    formGracePeriod.value = '10';
  }
  if (formEmployee && formEmployee.onchange) {
    formEmployee.onchange();
  }

  if (autoFilledProfile) {
    formFullName.value = autoFilledProfile.name || '';
    formDob.value = autoFilledProfile.date_of_birth || '';
    formMobileNumber.value = autoFilledProfile.mobile_number || '';
    formEmail.value = autoFilledProfile.email || '';
  } else {
    const aadhaarData = latestAadhaarPayload.aadhaar;
    formFullName.value = aadhaarData.full_name || '';
    formDob.value = aadhaarData.date_of_birth || '';
  }

  submitVisitorFormBtn.addEventListener('click', async () => {
    submitVisitorFormBtn.disabled = true;

    const formPayload = {
      visitor_id: visitorId,
      mobile_number: formMobileNumber.value,
      email: formEmail.value,
      purpose_of_visit: formPurpose.value,
      department: formDepartment.value,
      employee_to_meet: formEmployee.value,
      target_floor: formEmployee.selectedOptions[0] ? formEmployee.selectedOptions[0].dataset.floor : null,
      grace_period_minutes: formGracePeriod ? parseInt(formGracePeriod.value, 10) || 10 : 10,
      expected_duration: formDuration.value,
      vehicle_number: formVehicle.value,
    };

    try {
      const data = await apiRequest('/workflow/visitor/form', formPayload);
      visitorFormCard.innerHTML = `
        <h2>Visitor Entry Pass Generated Successfully!</h2>
        <p class="note">Authorized Session Key: <strong>${data.session_id}</strong>.</p>
        <img src="${data.qr_image_base64}" alt="Visitor Pass QR" style="max-width: 200px; margin: 1.5rem auto; display: block; border-radius: 8px;">
        <p style="text-align: center; color: var(--success)">Verification complete. Session activated under camera tracking surveillance networks.</p>
      `;
    } catch (error) {
      let displayError = error.message || 'Submission error';
      if (typeof error === 'object' && error.detail) {
        displayError = Array.isArray(error.detail) ? JSON.stringify(error.detail) : error.detail;
      }
      setMessage(`Error: ${displayError}`, 'error');
      submitVisitorFormBtn.disabled = false;
    }
  });
}

// --- SECURE SECURITY LOGIN CONTROL ACTIONS & LIVE PREVIEW HOOKS ---
const submitAdminAuthBtn = document.getElementById('submitAdminAuthBtn');
if (submitAdminAuthBtn) {
  submitAdminAuthBtn.addEventListener('click', async () => {
    const username = document.getElementById('adminUsername').value.trim();
    const password = document.getElementById('adminPassword').value.trim();
    const errorMsg = document.getElementById('authErrorMessage');
    
    try {
      const response = await apiRequest('/workflow/admin/login', { username, password });
      if (response.status === "success") {
        document.getElementById('adminAuthGateCard').classList.add('hidden');
        document.getElementById('adminDashboardCard').classList.remove('hidden');
        const facultyRegCard = document.getElementById('facultyRegistrationCard');
        if (facultyRegCard) {
          facultyRegCard.classList.remove('hidden');
          refreshRegisteredFaculty();
          // Live-refresh so verification status flips to "Verified" as soon
          // as a faculty member completes Aadhaar + face at their desk.
          if (!window._facultyDirectoryPoller) {
            window._facultyDirectoryPoller = setInterval(refreshRegisteredFaculty, 3000);
          }
        }
        initializeAdminSurveillancePolling();

        // Drive the entrance feed from the auto-detected camera registry, and
        // keep it in sync as the phone's IP changes (no hardcoded IP).
        refreshEntranceFeed();
        if (!window._entranceFeedPoller) {
          window._entranceFeedPoller = setInterval(refreshEntranceFeed, 5000);
        }

        startInBrowserVideoProcessing();
      }
    } catch (err) {
      errorMsg.textContent = err.detail || "Authentication processing failed.";
      errorMsg.classList.remove('hidden');
    }
  });
}

// --- CENTRAL ADMINISTRATOR TELEMETRY POLLING ENGINE (single source of truth) ---
// NOTE: previously two competing loops wrote to #surveillanceLogBody — one
// inserted rows, the other wiped the table every second with innerHTML=''
// and had no error handling, so matched visitors never stayed visible.
// This is now ONE robust renderer.
let _surveillancePollingStarted = false;
// Track the newest server-side detection so the live overlay/panel can be
// driven from real detections and auto-hidden when the feed goes quiet.
let _lastSurveillanceStamp = null;
let _lastSurveillanceSeenAt = 0;

function initializeAdminSurveillancePolling() {
  if (_surveillancePollingStarted) return;
  const logBody = document.getElementById('surveillanceLogBody');
  if (!logBody) return;
  _surveillancePollingStarted = true;

  setInterval(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/workflow/logs/surveillance`);
      if (!response.ok) return;

      const logs = await response.json();
      if (!Array.isArray(logs)) return;

      if (logs.length === 0) {
        logBody.innerHTML =
          '<tr id="emptySurveillanceRow"><td colspan="6" class="log-table__empty">Awaiting camera identification events...</td></tr>';
        return;
      }

      // Full re-render each tick (newest first, backend already reverses).
      const rowsHtml = logs.map((log) => {
        const timeFormatted = log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : '—';
        const cameraLabel = (log.camera_id || '—').replace(/_/g, ' ');
        const targetLabel = log.target_floor === null || log.target_floor === undefined
          ? '—' : `Target: Floor ${log.target_floor}`;
        return `<tr style="border-bottom: 1px solid rgba(255,255,255,0.05); background: ${log.alert_flag ? 'rgba(239, 68, 68, 0.08)' : 'transparent'};">
          <td style="padding: 12px 16px; color: var(--muted);">${timeFormatted}</td>
          <td style="padding: 12px 16px; font-weight: bold; color: #ffffff;">${log.name || '—'}</td>
          <td style="padding: 12px 16px; font-family: monospace; color: var(--accent); font-size: 0.8rem;">${log.visitor_id || '—'}</td>
          <td style="padding: 12px 16px; color: #e2e8f0;">${cameraLabel}</td>
          <td style="padding: 12px 16px; font-weight: 600; color: #f8fafc;">Floor ${log.current_floor} <small style="color: var(--muted);">(${targetLabel})</small></td>
          <td style="padding: 12px 16px; color: ${log.alert_flag ? '#ef4444' : '#10b981'}; font-weight: 600;">${log.alert_message || ''}</td>
        </tr>`;
      }).join('');

      logBody.innerHTML = rowsHtml;

      // --- REAL-TIME ON-FEED OVERLAY + MATCHED-VISITOR PANEL ---
      // The browser can't re-capture the cross-origin IP-cam frame (CORS
      // taints the canvas), so the live overlay is driven here from the
      // server-side detections instead. The newest entry (logs[0]) is the
      // most recent camera match; show it, and auto-hide once detections
      // stop arriving (feed went quiet for a few seconds).
      const latest = logs[0];
      if (latest) {
        const stamp = latest.id || latest.timestamp;
        if (stamp !== _lastSurveillanceStamp) {
          _lastSurveillanceStamp = stamp;
          _lastSurveillanceSeenAt = Date.now();
        }
        const fresh = Date.now() - _lastSurveillanceSeenAt < 6000;
        if (fresh && typeof showOverlay === 'function') {
          showOverlay(latest.name, latest.current_floor, latest.target_floor);
          updateDetectedPanel({
            name: latest.name,
            visitor_id: latest.visitor_id,
            current_floor: latest.current_floor,
            target_floor: latest.target_floor,
            department: latest.department,
            employee_to_meet: latest.employee_to_meet,
            purpose_of_visit: latest.purpose_of_visit,
          });
        } else if (!fresh && typeof hideOverlay === 'function') {
          hideOverlay();
          clearDetectedPanel();
        }
      }
    } catch (err) {
      // Network hiccup — keep the last rendered state and retry next tick.
      console.warn('Telemetry engine polling skip:', err);
    }
  }, 1000);
}

// Start polling immediately so matches appear even before admin login,
// and again (idempotently) after login.
initializeAdminSurveillancePolling();

// =====================================================================
// ADMIN: FACULTY REGISTRATION (writes to college.db faculty_registration)
// =====================================================================
const registerFacultyBtn = document.getElementById('registerFacultyBtn');
const regFacMessage = document.getElementById('regFacMessage');
const registeredFacultyBody = document.getElementById('registeredFacultyBody');

async function refreshRegisteredFaculty() {
  if (!registeredFacultyBody) return;
  try {
    const response = await fetch(`${API_BASE_URL}/workflow/admin/faculty/registered`);
    if (!response.ok) return;
    const faculty = await response.json();

    if (!faculty || faculty.length === 0) {
      registeredFacultyBody.innerHTML =
        '<tr><td colspan="7" class="log-table__empty">No faculty registered yet. Use the form above to add the first record.</td></tr>';
      return;
    }

    registeredFacultyBody.innerHTML = faculty.map((f) => `
      <tr>
        <td style="font-family: monospace;">${f.employee_id}</td>
        <td style="font-weight: bold;">${f.name}</td>
        <td>${f.department}</td>
        <td>${f.phone_number}</td>
        <td>Room ${f.room_number} / Floor ${f.assigned_floor}</td>
        <td>${f.masked_aadhaar}</td>
        <td style="color: ${f.is_verified ? '#10b981' : '#f59e0b'}; font-weight: 600;">
          ${f.is_verified ? 'Aadhaar + Face Verified' : 'Pending self-verification'}
        </td>
      </tr>
    `).join('');
  } catch (err) {
    // Keep last state; retried on next registration or login.
  }
}

if (registerFacultyBtn) {
  registerFacultyBtn.addEventListener('click', async () => {
    const payload = {
      employee_id: document.getElementById('regFacEmployeeId').value.trim(),
      name: document.getElementById('regFacName').value.trim(),
      department: document.getElementById('regFacDepartment').value.trim(),
      designation: document.getElementById('regFacDesignation').value.trim() || null,
      phone_number: document.getElementById('regFacPhone').value.trim(),
      email: document.getElementById('regFacEmail').value.trim() || null,
      room_number: document.getElementById('regFacRoom').value.trim(),
      assigned_floor: parseInt(document.getElementById('regFacFloor').value, 10),
      aadhaar_number: document.getElementById('regFacAadhaar').value.trim() || null,
    };

    if (!payload.employee_id || !payload.name || !payload.department ||
        !payload.phone_number || !payload.room_number || Number.isNaN(payload.assigned_floor)) {
      regFacMessage.textContent = 'Please fill all required (*) fields, including a valid floor number.';
      regFacMessage.style.color = 'var(--danger)';
      return;
    }

    registerFacultyBtn.disabled = true;
    registerFacultyBtn.textContent = 'Registering...';

    try {
      const data = await apiRequest('/workflow/admin/faculty/register', payload);
      regFacMessage.textContent = data.msg;
      regFacMessage.style.color = 'var(--verify)';
      ['regFacEmployeeId', 'regFacName', 'regFacDepartment', 'regFacDesignation',
       'regFacPhone', 'regFacEmail', 'regFacRoom', 'regFacFloor', 'regFacAadhaar']
        .forEach((id) => { const el = document.getElementById(id); if (el) el.value = ''; });
      refreshRegisteredFaculty();
    } catch (error) {
      regFacMessage.textContent = error.detail || 'Faculty registration failed.';
      regFacMessage.style.color = 'var(--danger)';
    }

    registerFacultyBtn.disabled = false;
    registerFacultyBtn.textContent = 'Register Faculty Member';
  });
}

// =====================================================================
// ADMIN ALERT ESCALATION PANEL
// Flow: Admin Alert -> Send Alert to Security -> Detain Visitor -> Blocked
// =====================================================================
const securityAlertsBody = document.getElementById('securityAlertsBody');

async function refreshSecurityAlerts() {
  if (!securityAlertsBody) return;
  try {
    const response = await fetch(`${API_BASE_URL}/workflow/admin/security-alerts`);
    if (!response.ok) return;
    const alerts = await response.json();

    securityAlertsBody.innerHTML = '';

    if (!alerts || alerts.length === 0) {
      securityAlertsBody.innerHTML =
        '<tr><td colspan="6" class="log-table__empty">No active security alerts. All visitors are within permitted zones.</td></tr>';
      return;
    }

    alerts.forEach((alertItem) => {
      const row = document.createElement('tr');
      const actionCell = alertItem.security_dispatched
        ? `<button data-detain-id="${alertItem.alert_id}" style="background: linear-gradient(135deg, var(--danger), #b91c1c); color: #fff;">Detain Visitor &amp; Block</button>
           <div style="font-size: 0.75rem; margin-top: 4px;">Security team alerted — awaiting detain confirmation</div>`
        : `<button data-dispatch-id="${alertItem.alert_id}">Send Alert to Security</button>`;

      row.innerHTML = `
        <td>${alertItem.timestamp ? new Date(alertItem.timestamp).toLocaleTimeString() : '—'}</td>
        <td>${alertItem.visitor_name}<br><small>${alertItem.visitor_ref || ''}</small></td>
        <td>${alertItem.employee_to_meet}<br><small>${alertItem.department || ''}</small></td>
        <td>Floor ${alertItem.current_floor}</td>
        <td>${alertItem.message}</td>
        <td>${actionCell}</td>
      `;
      securityAlertsBody.appendChild(row);
    });
  } catch (err) {
    // Network hiccup — keep the previous table state and retry next tick.
  }
}

if (securityAlertsBody) {
  securityAlertsBody.addEventListener('click', async (event) => {
    const dispatchId = event.target.getAttribute('data-dispatch-id');
    const detainId = event.target.getAttribute('data-detain-id');

    if (dispatchId) {
      event.target.disabled = true;
      event.target.textContent = 'Dispatching Security...';
      try {
        const data = await apiRequest(`/workflow/admin/security-alerts/${dispatchId}/dispatch-security`, {});
        alert(data.msg || 'Alert forwarded to the security team.');
      } catch (error) {
        alert(error.detail || 'Failed to dispatch security.');
      }
      refreshSecurityAlerts();
    }

    if (detainId) {
      const confirmed = window.confirm(
        'Confirm final escalation: security will detain this visitor and the admin will BLOCK them. Proceed?'
      );
      if (!confirmed) return;
      event.target.disabled = true;
      event.target.textContent = 'Detaining...';
      try {
        const data = await apiRequest(`/workflow/admin/security-alerts/${detainId}/detain`, {});
        alert(data.msg || 'Visitor detained and blocked.');
      } catch (error) {
        alert(error.detail || 'Failed to detain visitor.');
      }
      refreshSecurityAlerts();
    }
  });

  refreshSecurityAlerts();
  setInterval(refreshSecurityAlerts, 3000);
}

// --- DYNAMIC IP ROUTER LIVE SYNC MATRIX FOR CAM VIEW ---
if (syncCamIpBtn && dynamicCamIpInput && adminLiveFeedFrame) {
  syncCamIpBtn.addEventListener('click', () => {
    let targetIp = dynamicCamIpInput.value.trim();
    if (!targetIp) {
      alert("Specify dynamic IP allocated to your smartphone node.");
      return;
    }

    // Standardize URL protocol
    if (!targetIp.startsWith('http://')) targetIp = 'http://' + targetIp;
    if (!targetIp.includes(':8080')) targetIp = targetIp + ':8080';
    if (!targetIp.endsWith('/video')) targetIp = targetIp + '/video';
    
    adminLiveFeedFrame.src = targetIp;
    adminLiveFeedFrame.style.border = '2px solid #2563eb';
    
    if (streamStatusIndicator) {
      streamStatusIndicator.textContent = '🔄 LIVE MONITORING ACTIVE';
      streamStatusIndicator.style.color = '#3b82f6';
    }
  });
}

// --- SECURE WORKSPACE AREA INTERFACE SELECTOR TOGGLES ---
const toggleFacultyViewBtn = document.getElementById('toggleFacultyViewBtn');
const facultyWorkspaceView = document.getElementById('facultyWorkspaceView');

function resetModeButtons() {
  [toggleVisitorViewBtn, toggleFacultyViewBtn, toggleAdminViewBtn].forEach((btn) => {
    if (btn) btn.style.background = 'rgba(255,255,255,0.05)';
  });
  [visitorWorkspaceView, facultyWorkspaceView, adminWorkspaceView].forEach((view) => {
    if (view) view.classList.add('hidden');
  });
}

if (toggleVisitorViewBtn && toggleAdminViewBtn) {
  toggleVisitorViewBtn.addEventListener('click', () => {
    resetModeButtons();
    toggleVisitorViewBtn.style.background = 'linear-gradient(135deg, var(--accent), #1d4ed8)';
    visitorWorkspaceView.classList.remove('hidden');
  });

  if (toggleFacultyViewBtn) {
    toggleFacultyViewBtn.addEventListener('click', () => {
      resetModeButtons();
      toggleFacultyViewBtn.style.background = 'linear-gradient(135deg, #059669, #10b981)';
      if (facultyWorkspaceView) facultyWorkspaceView.classList.remove('hidden');
    });
  }

  toggleAdminViewBtn.addEventListener('click', () => {
    resetModeButtons();
    toggleAdminViewBtn.style.background = 'linear-gradient(135deg, var(--danger), #b91c1c)';
    adminWorkspaceView.classList.remove('hidden');
  });
}

// =============================
// LIVE FACE OVERLAY ON CAMERA
// =============================

const faceOverlay = document.getElementById("faceOverlay");
const overlayName = document.getElementById("overlayName");
const overlayFloors = document.getElementById("overlayFloors");

// Detail panel shown below the live feed with the full matched record
const detectedPersonPanel = document.getElementById("detectedPersonPanel");
const detectedStatusBadge = document.getElementById("detectedStatusBadge");
const detectedName = document.getElementById("detectedName");
const detectedVisitorId = document.getElementById("detectedVisitorId");
const detectedDepartment = document.getElementById("detectedDepartment");
const detectedPersonToMeet = document.getElementById("detectedPersonToMeet");
const detectedCurrentFloor = document.getElementById("detectedCurrentFloor");
const detectedTargetFloor = document.getElementById("detectedTargetFloor");
const detectedPurpose = document.getElementById("detectedPurpose");
const detectedLastSeen = document.getElementById("detectedLastSeen");

// Populates the panel from whatever fields the /workflow/tracking/stream-reid
// response includes. Fields the backend doesn't send yet just show as "—".
function updateDetectedPanel(data) {
    if (!detectedPersonPanel) return;

    detectedPersonPanel.classList.remove("hidden");

    detectedName.textContent = data.name || "Unknown";
    detectedVisitorId.textContent = data.visitor_id || "—";
    detectedDepartment.textContent = data.department || "—";
    detectedPersonToMeet.textContent = data.employee_to_meet || data.person_to_meet || "—";
    detectedCurrentFloor.textContent = data.current_floor != null ? `Floor ${data.current_floor}` : "—";
    detectedTargetFloor.textContent = data.target_floor != null ? `Floor ${data.target_floor}` : "—";
    detectedPurpose.textContent = data.purpose_of_visit || "—";
    detectedLastSeen.textContent = new Date().toLocaleTimeString();

    const mismatch = data.target_floor != null && Number(data.current_floor) !== Number(data.target_floor);
    detectedStatusBadge.textContent = mismatch ? "🚨 Unauthorized Floor" : "✅ Authorized";
    detectedStatusBadge.classList.toggle("is-danger", mismatch);
    detectedStatusBadge.classList.toggle("is-success", !mismatch);
}

function clearDetectedPanel() {
    if (!detectedPersonPanel) return;
    detectedPersonPanel.classList.add("hidden");
}

const CURRENT_CAMERA_FLOOR = 1;
const CAMERA_ID = "Camera_Node_1_Entrance";

function showOverlay(name, currentFloor, targetFloor) {
    overlayName.textContent = `👤 ${name}`;

    overlayFloors.innerHTML =
        `<strong>Current Floor:</strong> ${currentFloor}` +
        (targetFloor != null
            ? `<br><strong>Target Floor:</strong> ${targetFloor}`
            : "");

    faceOverlay.style.borderLeftColor =
        (targetFloor != null && Number(currentFloor) !== Number(targetFloor))
            ? "#ef4444"
            : "#10b981";

    faceOverlay.classList.remove("hidden");
}

function hideOverlay() {
    faceOverlay.classList.add("hidden");
}

function captureFeedFrameBase64() {

    if (!adminLiveFeedFrame) return null;

    const canvas = document.createElement("canvas");

    canvas.width = adminLiveFeedFrame.naturalWidth;
    canvas.height = adminLiveFeedFrame.naturalHeight;

    if (!canvas.width || !canvas.height)
        return null;

    try {

        const ctx = canvas.getContext("2d");

        ctx.drawImage(
            adminLiveFeedFrame,
            0,
            0,
            canvas.width,
            canvas.height
        );

        return canvas.toDataURL("image/jpeg").split(",")[1];

    } catch (e) {

        console.error("Frame capture blocked by CORS", e);
        return null;
    }
}

async function runLiveFaceIdentification() {

    const frame = captureFeedFrameBase64();

    if (!frame) {
        console.warn("No frame captured.");
        return;
    }

    try {

        const response = await fetch(
            `${API_BASE_URL}/workflow/tracking/stream-reid`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    camera_id: CAMERA_ID,
                    current_floor: CURRENT_CAMERA_FLOOR,
                    frame_image_base64: frame
                })
            }
        );

        const data = await response.json();

        console.log("Recognition Response:", data);

        if (response.ok && data.identified) {

            showOverlay(
                data.name,
                data.current_floor,
                data.target_floor
            );
            updateDetectedPanel(data);

        } else {

            hideOverlay();
            clearDetectedPanel();

        }

    } catch (err) {

        console.error("Recognition Error:", err);
        hideOverlay();
        clearDetectedPanel();

    }

}

setInterval(runLiveFaceIdentification, 2500);

// =====================================================================
// FACULTY VERIFICATION FLOW (mirrors visitor Aadhaar + face pipeline)
// =====================================================================

const facultyEmployeeIdInput = document.getElementById('facultyEmployeeId');
const facultyAadhaarNumberInput = document.getElementById('facultyAadhaarNumber');
const facultySendOtpBtn = document.getElementById('facultySendOtpBtn');
const facultyOtpRow = document.getElementById('facultyOtpRow');
const facultyOtpInput = document.getElementById('facultyOtpInput');
const facultyVerifyBtn = document.getElementById('facultyVerifyBtn');
const facultyMessageBox = document.getElementById('facultyMessageBox');
const facultyAadhaarCard = document.getElementById('facultyAadhaarCard');

const facultyFaceCard = document.getElementById('facultyFaceCard');
const facultyFaceCardTitle = document.getElementById('facultyFaceCardTitle');
const facultyFaceMessage = document.getElementById('facultyFaceMessage');
const facultyVideoPreview = document.getElementById('facultyVideoPreview');
const facultyFaceGuide = document.getElementById('facultyFaceGuide');
const facultyRegistrationControls = document.getElementById('facultyRegistrationControls');
const facultyRevisitControls = document.getElementById('facultyRevisitControls');
const facultyCaptureFrontBtn = document.getElementById('facultyCaptureFrontBtn');
const facultyCaptureLeftBtn = document.getElementById('facultyCaptureLeftBtn');
const facultyCaptureRightBtn = document.getElementById('facultyCaptureRightBtn');
  const facultyRegisterFaceBtn = document.getElementById('facultyRegisterFaceBtn');
  const facultyAuthenticateFaceBtn = document.getElementById('facultyAuthenticateFaceBtn');
  const facultyRegisterNewFaceBtn = document.getElementById('facultyRegisterNewFaceBtn');

const facultyVerifiedCard = document.getElementById('facultyVerifiedCard');
const facultyVerifiedSummary = document.getElementById('facultyVerifiedSummary');
const facultyVerifiedName = document.getElementById('facultyVerifiedName');
const facultyVerifiedEmpId = document.getElementById('facultyVerifiedEmpId');
const facultyVerifiedDept = document.getElementById('facultyVerifiedDept');
const facultyVerifiedFloor = document.getElementById('facultyVerifiedFloor');

let facultyFlowId = '';
let facultyIsRevisitMode = false;
let facultyCapturedImages = { front: null, left: null, right: null };

function setFacultyMessage(text, tone = 'info') {
  if (!facultyMessageBox) return;
  facultyMessageBox.textContent = text;
  facultyMessageBox.style.color =
    tone === 'error' ? 'var(--danger)' : tone === 'success' ? 'var(--verify)' : 'var(--fog)';
}

if (facultySendOtpBtn) {
  facultySendOtpBtn.addEventListener('click', async () => {
    const employee_id = facultyEmployeeIdInput.value.trim();
    const aadhaar_number = facultyAadhaarNumberInput.value.trim();

    if (!employee_id) {
      setFacultyMessage('Please enter your Employee ID.', 'error');
      return;
    }

    const digilockerWindow = window.open('', '_blank');
    setFacultyMessage('Verifying employee record and processing Aadhaar...');

    try {
      const data = await apiRequest('/workflow/faculty/aadhaar/start', { employee_id, aadhaar_number });

      if (data.pre_verified) {
        facultyIsRevisitMode = true;
        setFacultyMessage(data.message, 'success');
        startFacultyFaceStep();
      } else {
        facultyIsRevisitMode = false;
        facultyFlowId = data.flow_id;
        if (data.authorization_url) {
          if (digilockerWindow) {
            digilockerWindow.location = data.authorization_url;
          } else {
            window.open(data.authorization_url, '_blank');
          }
        }
        facultyOtpRow.classList.remove('hidden');
        facultyOtpInput.classList.add('hidden');
        facultyVerifyBtn.textContent = 'Verify DigiLocker';
        setFacultyMessage('Complete Aadhaar OTP and consent in the DigiLocker window, then click Verify DigiLocker.', 'success');
      }
    } catch (error) {
      if (digilockerWindow) digilockerWindow.close();
      setFacultyMessage(error.detail || error.error || 'Faculty identity lookup failure.', 'error');
    }
  });
}

if (facultyVerifyBtn) {
  facultyVerifyBtn.addEventListener('click', async () => {
    setFacultyMessage('Verifying OTP...');

    try {
      const data = await apiRequest('/workflow/faculty/aadhaar/verify', {
        employee_id: facultyEmployeeIdInput.value.trim(),
        flow_id: facultyFlowId,
        otp: '',
      });

      setFacultyMessage(data.message || 'Aadhaar verified. Proceed to face registration.', 'success');
      startFacultyFaceStep();
    } catch (error) {
      const message = error.detail || error.error || 'OTP verification exception.';
      if (String(message).toLowerCase().includes('expired')) {
        facultyFlowId = '';
        facultyOtpInput.value = '';
        setFacultyMessage('This OTP has expired. Click Verify Faculty & Send OTP to request a new OTP, then enter only the latest code.', 'error');
      } else {
        setFacultyMessage(message, 'error');
      }
    }
  });
}

async function startFacultyFaceStep() {
  facultyAadhaarCard.classList.add('hidden');
  facultyFaceCard.classList.remove('hidden');

  if (facultyIsRevisitMode) {
    facultyFaceCardTitle.textContent = 'Faculty Identity Verification Check';
    facultyFaceMessage.textContent = 'Gaze into the viewport for instant face authentication.';
    facultyRegistrationControls.classList.add('hidden');
    facultyRevisitControls.classList.remove('hidden');
    facultyRegisterFaceBtn.classList.add('hidden');
  } else {
    facultyFaceCardTitle.textContent = 'Faculty Face Enrollment Registration';
    facultyFaceMessage.textContent = 'Complete the standard three-angle capture sequence.';
    facultyRegistrationControls.classList.remove('hidden');
    facultyRevisitControls.classList.add('hidden');
    facultyRegisterFaceBtn.classList.remove('hidden');
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    facultyVideoPreview.srcObject = stream;
    facultyVideoPreview.play();
  } catch (err) {
    facultyFaceMessage.textContent = `Webcam runtime blocked: ${err.message}.`;
    facultyFaceMessage.style.color = 'var(--danger)';
  }
}

function captureFacultyFrameBase64() {
  const canvas = document.createElement('canvas');
  canvas.width = facultyVideoPreview.videoWidth;
  canvas.height = facultyVideoPreview.videoHeight;
  canvas.getContext('2d').drawImage(facultyVideoPreview, 0, 0);
  return canvas.toDataURL('image/jpeg').split(',')[1];
}

const facultyRetryCaptureBtn = document.getElementById('facultyRetryCaptureBtn');

function checkFacultyAllCaptured() {
  if (facultyCapturedImages.front && facultyCapturedImages.left && facultyCapturedImages.right) {
    facultyRegisterFaceBtn.disabled = false;
    facultyFaceMessage.textContent = 'Facial profiles captured. Ready to submit registration data.';
  }
}

function showFacultyRetryButton() {
  if (facultyRetryCaptureBtn) facultyRetryCaptureBtn.classList.remove('hidden');
}

function resetFacultyCaptures() {
  facultyCapturedImages = { front: null, left: null, right: null };
  facultyRegisterFaceBtn.disabled = true;
  if (facultyCaptureFrontBtn) {
    facultyCaptureFrontBtn.textContent = 'Capture Front';
    facultyCaptureFrontBtn.disabled = false;
  }
  if (facultyCaptureLeftBtn) {
    facultyCaptureLeftBtn.textContent = 'Capture Left';
    facultyCaptureLeftBtn.disabled = false;
  }
  if (facultyCaptureRightBtn) {
    facultyCaptureRightBtn.textContent = 'Capture Right';
    facultyCaptureRightBtn.disabled = false;
  }
  facultyFaceGuide.classList.remove('danger', 'success');
  facultyFaceMessage.textContent = 'Captures cleared. Position your face clearly in the center and capture all three angles again.';
  facultyFaceMessage.style.color = 'var(--fog)';
}

if (facultyRetryCaptureBtn) {
  facultyRetryCaptureBtn.addEventListener('click', resetFacultyCaptures);
}

if (facultyCaptureFrontBtn) {
  facultyCaptureFrontBtn.addEventListener('click', () => {
    facultyCapturedImages.front = captureFacultyFrameBase64();
    facultyCaptureFrontBtn.textContent = 'Front ✓';
    facultyCaptureFrontBtn.disabled = true;
    showFacultyRetryButton();
    checkFacultyAllCaptured();
  });
}

if (facultyCaptureLeftBtn) {
  facultyCaptureLeftBtn.addEventListener('click', () => {
    facultyCapturedImages.left = captureFacultyFrameBase64();
    facultyCaptureLeftBtn.textContent = 'Left ✓';
    facultyCaptureLeftBtn.disabled = true;
    showFacultyRetryButton();
    checkFacultyAllCaptured();
  });
}

if (facultyCaptureRightBtn) {
  facultyCaptureRightBtn.addEventListener('click', () => {
    facultyCapturedImages.right = captureFacultyFrameBase64();
    facultyCaptureRightBtn.textContent = 'Right ✓';
    facultyCaptureRightBtn.disabled = true;
    showFacultyRetryButton();
    checkFacultyAllCaptured();
  });
}

function showFacultyVerifiedCard(data) {
  if (facultyVideoPreview.srcObject) {
    facultyVideoPreview.srcObject.getTracks().forEach((track) => track.stop());
  }
  facultyFaceCard.classList.add('hidden');
  facultyVerifiedCard.classList.remove('hidden');
  facultyVerifiedSummary.textContent = data.status || 'Faculty verification complete.';
  facultyVerifiedName.textContent = data.name || '—';
  facultyVerifiedEmpId.textContent = data.employee_id || '—';
  facultyVerifiedDept.textContent = data.department || '—';
  facultyVerifiedFloor.textContent = data.assigned_floor != null ? `Floor ${data.assigned_floor}` : '—';

  // Remember who's logged in so the edit form + visitor tracking can target them.
  window._verifiedFacultyId = data.employee_id || '';
  window._verifiedFacultyName = data.name || '';
  const editDept = document.getElementById('facEditDept');
  const editFloor = document.getElementById('facEditFloor');
  if (editDept) editDept.value = data.department || '';
  if (editFloor && data.assigned_floor != null) editFloor.value = data.assigned_floor;

  startFacultyVisitorsPolling();
}

if (facultyRegisterFaceBtn) {
  facultyRegisterFaceBtn.addEventListener('click', async () => {
    facultyRegisterFaceBtn.disabled = true;
    try {
      const data = await apiRequest('/workflow/faculty/face/register', {
        employee_id: facultyEmployeeIdInput.value.trim(),
        front_image_base64: facultyCapturedImages.front,
        left_image_base64: facultyCapturedImages.left,
        right_image_base64: facultyCapturedImages.right,
        blink_done: true,
        turn_left_done: true,
        turn_right_done: true,
        is_revisit: false,
      });
      facultyFaceGuide.classList.add('success');
      showFacultyVerifiedCard(data);
    } catch (error) {
      const displayError = (typeof error === 'object' && error.detail)
        ? (Array.isArray(error.detail) ? JSON.stringify(error.detail) : error.detail)
        : (error.message || 'Registration error occurred');
      facultyFaceMessage.textContent = `${displayError} — click "Retry Capture" to recapture all three angles.`;
      facultyFaceMessage.style.color = 'var(--danger)';
      facultyFaceGuide.classList.add('danger');
      // Keep Register disabled: the captured frames were rejected by the
      // backend (face not visible/clear), so a fresh capture is required.
      facultyRegisterFaceBtn.disabled = true;
      showFacultyRetryButton();
    }
  });
}

if (facultyAuthenticateFaceBtn) {
  facultyAuthenticateFaceBtn.addEventListener('click', async () => {
    facultyAuthenticateFaceBtn.disabled = true;
    facultyFaceMessage.textContent = 'Matching live values against the faculty facial registry...';
    facultyFaceGuide.classList.remove('danger', 'success');

    try {
      const data = await apiRequest('/workflow/faculty/face/register', {
        employee_id: facultyEmployeeIdInput.value.trim(),
        front_image_base64: captureFacultyFrameBase64(),
        blink_done: true,
        is_revisit: true,
      });
      facultyFaceGuide.classList.add('success');
      showFacultyVerifiedCard(data);
    } catch (error) {
      const displayError = (typeof error === 'object' && error.detail)
        ? (Array.isArray(error.detail) ? JSON.stringify(error.detail) : error.detail)
        : (error.message || 'Authentication failure');
      facultyFaceMessage.textContent = `Authentication Refused: ${displayError} — adjust your position and press the button to retry, or register a new face.`;
      facultyFaceMessage.style.color = 'var(--danger)';
      facultyFaceGuide.classList.add('danger');
      facultyAuthenticateFaceBtn.disabled = false;
      facultyAuthenticateFaceBtn.textContent = 'Retry Face Authentication';
      if (facultyRegisterNewFaceBtn) facultyRegisterNewFaceBtn.classList.remove('hidden');
    }
  });
}

if (facultyRegisterNewFaceBtn) {
  facultyRegisterNewFaceBtn.addEventListener('click', () => {
    // Switch from authentication (revisit) mode into a fresh face enrollment.
    facultyIsRevisitMode = false;
    facultyRegisterNewFaceBtn.classList.add('hidden');
    facultyRevisitControls.classList.add('hidden');
    facultyRegistrationControls.classList.remove('hidden');
    facultyRegisterFaceBtn.classList.remove('hidden');
    if (facultyRetryCaptureBtn) facultyRetryCaptureBtn.classList.add('hidden');
    facultyFaceCardTitle.textContent = 'Faculty Face Enrollment Registration';
    facultyAuthenticateFaceBtn.textContent = 'Verify & Authenticate Face';
    facultyAuthenticateFaceBtn.disabled = false;
    resetFacultyCaptures();
    facultyFaceMessage.textContent = 'Re-enrolling face. Complete the three-angle capture sequence again.';
    facultyFaceMessage.style.color = 'var(--fog)';
  });
}

// =====================================================================
// FACULTY SELF-SERVICE EDIT + "MY VISITORS" LIVE TRACKING
// =====================================================================
const facSaveDetailsBtn = document.getElementById('facSaveDetailsBtn');
const facEditMessage = document.getElementById('facEditMessage');

if (facSaveDetailsBtn) {
  facSaveDetailsBtn.addEventListener('click', async () => {
    const employee_id = window._verifiedFacultyId;
    if (!employee_id) {
      facEditMessage.textContent = 'Verify your identity first, then edit your details.';
      facEditMessage.style.color = 'var(--danger)';
      return;
    }
    const floorRaw = document.getElementById('facEditFloor').value.trim();
    const payload = {
      employee_id,
      department: document.getElementById('facEditDept').value.trim() || null,
      room_number: document.getElementById('facEditRoom').value.trim() || null,
      assigned_floor: floorRaw === '' ? null : parseInt(floorRaw, 10),
      phone_number: document.getElementById('facEditPhone').value.trim() || null,
    };

    facSaveDetailsBtn.disabled = true;
    facSaveDetailsBtn.textContent = 'Saving...';
    try {
      const data = await apiRequest('/workflow/faculty/update-details', payload);
      facEditMessage.textContent = data.msg || 'Details updated.';
      facEditMessage.style.color = 'var(--verify)';
      // Reflect the new values in the verified-card summary.
      if (data.faculty) {
        if (facultyVerifiedDept) facultyVerifiedDept.textContent = data.faculty.department || '—';
        if (facultyVerifiedFloor) facultyVerifiedFloor.textContent =
          data.faculty.assigned_floor != null ? `Floor ${data.faculty.assigned_floor}` : '—';
      }
    } catch (error) {
      facEditMessage.textContent = (error && error.detail) || 'Failed to update details.';
      facEditMessage.style.color = 'var(--danger)';
    }
    facSaveDetailsBtn.disabled = false;
    facSaveDetailsBtn.textContent = 'Save My Details';
  });
}

let _facultyVisitorsPoller = null;
const facVisitorsBody = document.getElementById('facVisitorsBody');
const facVisitorFeedWrap = document.getElementById('facVisitorFeedWrap');
const facVisitorFeed = document.getElementById('facVisitorFeed');
const facVisitorFeedLabel = document.getElementById('facVisitorFeedLabel');

function startFacultyVisitorsPolling() {
  if (_facultyVisitorsPoller) return;   // already running
  refreshFacultyVisitors();
  _facultyVisitorsPoller = setInterval(refreshFacultyVisitors, 3000);
}

async function refreshFacultyVisitors() {
  const employee_id = window._verifiedFacultyId;
  if (!employee_id || !facVisitorsBody) return;
  try {
    const response = await fetch(`${API_BASE_URL}/workflow/faculty/${encodeURIComponent(employee_id)}/visitors`);
    if (!response.ok) return;
    const visitors = await response.json();

    if (!Array.isArray(visitors) || visitors.length === 0) {
      facVisitorsBody.innerHTML =
        '<tr><td colspan="6" class="log-table__empty">No visitors yet. You\'ll see them here the moment they check in to meet you.</td></tr>';
      if (facVisitorFeedWrap) facVisitorFeedWrap.classList.add('hidden');
      return;
    }

    facVisitorsBody.innerHTML = visitors.map((v) => {
      const arrived = v.arrival ? new Date(v.arrival).toLocaleTimeString() : '⏳ En route';
      const statusTxt = v.status === 'blocked'
        ? '🚫 Blocked'
        : (v.exited ? '✅ Left' : (v.in_room ? '🟢 In your room' : '👣 On campus'));
      const cam = v.current_camera_label || 'Not seen';
      return `<tr style="background:${v.in_room ? 'rgba(16,185,129,0.08)' : 'transparent'};">
        <td style="font-weight:bold;">${v.visitor_name || '—'}<br><small style="color:var(--muted);font-family:monospace;">${v.visitor_id || ''}</small></td>
        <td>${v.purpose_of_visit || '—'}</td>
        <td>${cam}${v.current_floor != null ? `<br><small>Floor ${v.current_floor}</small>` : ''}</td>
        <td>${arrived}</td>
        <td style="font-weight:600;">${v.wait_minutes != null ? v.wait_minutes : '0'}</td>
        <td>${statusTxt}</td>
      </tr>`;
    }).join('');

    // Show the camera feed where the most relevant visitor currently is:
    // prefer an in-room visitor, else the first still-present one.
    const focus = visitors.find((v) => v.in_room && v.stream_url)
      || visitors.find((v) => !v.exited && v.stream_url);
    if (focus && facVisitorFeedWrap && facVisitorFeed) {
      if (facVisitorFeed.src !== focus.stream_url) facVisitorFeed.src = focus.stream_url;
      if (facVisitorFeedLabel) facVisitorFeedLabel.textContent =
        `${focus.visitor_name} · ${focus.current_camera_label || ''}`;
      facVisitorFeedWrap.classList.remove('hidden');
    } else if (facVisitorFeedWrap) {
      facVisitorFeedWrap.classList.add('hidden');
    }
  } catch (err) {
    // keep last state on transient error
  }
}

// =====================================================================
// ADMIN: MULTI-CAMERA NODE GRID (GET /workflow/cameras + assign streams)
// =====================================================================
const cameraFeedsContainer = document.getElementById('cameraFeedsContainer');
let _renderedCameraIds = '';

async function refreshCameraNodes() {
  if (!cameraFeedsContainer) return;
  try {
    const response = await fetch(`${API_BASE_URL}/workflow/cameras`);
    if (!response.ok) return;
    const cameras = await response.json();
    if (!Array.isArray(cameras)) return;

    // Only re-render the grid structure when the set of cameras changes, so we
    // don't wipe an input the admin is typing into every poll.
    const signature = cameras.map((c) => `${c.camera_id}:${c.stream_url || ''}`).join('|');
    if (signature === _renderedCameraIds) return;
    _renderedCameraIds = signature;

    cameraFeedsContainer.innerHTML = cameras.map((c) => {
      const online = !!c.stream_url;
      return `<div class="camera-card" data-camera-id="${c.camera_id}">
        <div class="camera-card__head">
          <span class="camera-card__label">📹 ${c.label}</span>
          <span class="camera-card__status" style="color:${online ? '#10b981' : '#f59e0b'};">
            ${online ? '🟢 ONLINE' : '⚪ NO STREAM'}
          </span>
        </div>
        <div class="cam-feed-wrap">
          ${online
            ? `<img class="cam-feed-frame" src="${c.stream_url}" alt="${c.label} feed">`
            : `<div class="log-table__empty" style="padding:2rem 1rem;">Assign this camera's phone IP below to bring it online.</div>`}
          <div class="face-overlay hidden" data-overlay-for="${c.camera_id}" style="position:absolute;bottom:8px;left:8px;"></div>
        </div>
        <div class="stream-panel__sync" style="margin-top:0.5rem;">
          <input type="text" data-ip-for="${c.camera_id}" placeholder="e.g. 192.168.1.42" value="${c.stream_url ? '' : ''}">
          <button data-sync-for="${c.camera_id}">Sync Feed</button>
        </div>
        <small style="color:var(--muted);">Floor ${c.floor}${c.room_number ? ` · Room ${c.room_number}` : ''}</small>
      </div>`;
    }).join('');
  } catch (err) {
    // keep last state
  }
}

if (cameraFeedsContainer) {
  cameraFeedsContainer.addEventListener('click', async (event) => {
    const camId = event.target.getAttribute('data-sync-for');
    if (!camId) return;
    const input = cameraFeedsContainer.querySelector(`input[data-ip-for="${camId}"]`);
    const ip = input ? input.value.trim() : '';
    if (!ip) { alert('Enter the camera phone IP first.'); return; }
    event.target.disabled = true;
    event.target.textContent = 'Syncing...';
    try {
      await apiRequest(`/workflow/cameras/${encodeURIComponent(camId)}/stream`, { stream_url: ip });
      _renderedCameraIds = '';        // force re-render with the new stream
      await refreshCameraNodes();
    } catch (error) {
      alert((error && error.detail) || 'Failed to assign camera stream.');
      event.target.disabled = false;
      event.target.textContent = 'Sync Feed';
    }
  });

  // Update each camera card's overlay from the surveillance poll, grouped by camera.
  refreshCameraNodes();
  setInterval(refreshCameraNodes, 5000);
}

// "Auto-Detect Cameras on WiFi" — scans the LAN for IP Webcam phones and
// assigns them to any camera node that has no stream yet, so no IP typing.
const autoDetectCamsBtn = document.getElementById('autoDetectCamsBtn');
const autoDetectMessage = document.getElementById('autoDetectMessage');
if (autoDetectCamsBtn) {
  autoDetectCamsBtn.addEventListener('click', async () => {
    autoDetectCamsBtn.disabled = true;
    const original = autoDetectCamsBtn.textContent;
    autoDetectCamsBtn.textContent = '🔎 Scanning WiFi…';
    if (autoDetectMessage) {
      autoDetectMessage.style.display = 'block';
      autoDetectMessage.style.color = 'var(--muted)';
      autoDetectMessage.textContent = 'Scanning the local network for phones running IP Webcam…';
    }
    try {
      const result = await apiRequest('/workflow/cameras/auto-assign', {});
      const count = (result && result.assigned_count) || 0;
      if (autoDetectMessage) {
        if (count > 0) {
          autoDetectMessage.style.color = '#10b981';
          const list = (result.assigned || [])
            .map((a) => `${a.camera_id} → ${a.stream_url}`).join(', ');
          autoDetectMessage.textContent = `✅ Assigned ${count} camera(s): ${list}`;
        } else {
          autoDetectMessage.style.color = '#f59e0b';
          autoDetectMessage.textContent = '⚠️ No new phones found on the WiFi. Make sure IP Webcam is started on the phone and it is on the same network, then try again.';
        }
      }
      _renderedCameraIds = '';        // force a re-render with the new streams
      await refreshCameraNodes();
    } catch (error) {
      if (autoDetectMessage) {
        autoDetectMessage.style.color = '#ef4444';
        autoDetectMessage.textContent = (error && error.detail) || 'Auto-detect failed.';
      }
    } finally {
      autoDetectCamsBtn.disabled = false;
      autoDetectCamsBtn.textContent = original;
    }
  });
}
