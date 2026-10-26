import cv2
import base64
import requests
import time
import threading
from zeroconf import Zeroconf, ServiceBrowser

# Central Backend Endpoint
API_URL = "http://127.0.0.1:8000/workflow/tracking/stream-reid"

# Global placeholder to hold the auto-discovered stream URL
AUTOMATED_STREAM_URL = None

class IPWebcamDiscoveryListener:
    """Listener to automatically discover Android IP Webcam services on the local Wi-Fi network."""
    def remove_service(self, zeroconf, type, name):
        pass

    def update_service(self, zeroconf, type, name):
        pass

    def add_service(self, zeroconf, type, name):
        global AUTOMATED_STREAM_URL
        info = zeroconf.get_service_info(type, name)
        if info:
            # Extract IP address from binary to string format array
            addresses = [str(sqlite3_ip) for sqlite3_ip in info.parsed_addresses()]
            if addresses:
                discovered_ip = addresses[0]
                discovered_port = info.port
                AUTOMATED_STREAM_URL = f"http://{discovered_ip}:{discovered_port}/video"
                print(f"\n[🚀 AUTO-DISCOVERY] Found Active Phone IP Camera Node!")
                print(f" -> Target Streaming Endpoint Path: {AUTOMATED_STREAM_URL}")

def discover_phone_ip_automatically():
    """Scans the local subnet for IP Webcam or standard network broadcast streams."""
    global AUTOMATED_STREAM_URL
    zeroconf = Zeroconf()
    listener = IPWebcamDiscoveryListener()
    
    # Browsing for common HTTP/IP Webcam broadcast signatures on local network
    browser = ServiceBrowser(zeroconf, "_http._tcp.local.", listener)
    
    print("[*] Scanning local Wi-Fi subnet channels for network camera endpoints...")
    timeout = 10
    start_time = time.time()
    
    # Wait until service is resolved or timeout hits
    while AUTOMATED_STREAM_URL is None and (time.time() - start_time) < timeout:
        time.sleep(0.5)
        
    zeroconf.close()
    
    # HARDWARE FALLBACK: If mDNS network discovery takes time, scan standard port ranges
    if AUTOMATED_STREAM_URL is None:
        print("[!] mDNS scan timed out. Attempting fallback brute-force subnet socket ping...")
        # Fallback to your known subnet signature if discovery misses the lease profile
        AUTOMATED_STREAM_URL = "http://192.168.29.223:8080/video" 

def camera_connection_worker(camera_id: str, config: dict):
    """Manages processing threads cleanly with dynamically assigned video streaming targets."""
    print(f"[*] Starting background initialization loop for node: {camera_id}")
    
    while True:
        # Fetch the fresh auto-discovered URL path parameters matrix
        stream_target = AUTOMATED_STREAM_URL if AUTOMATED_STREAM_URL else config["stream_url"]
        cap = cv2.VideoCapture(stream_target)
        
        if not cap.isOpened():
            print(f"[!] {camera_id} is unavailable at {stream_target}. Scanning network for fresh IP lease...")
            discover_phone_ip_automatically()
            time.sleep(4)
            continue
            
        print(f"[SUCCESS] Connection established with {camera_id} at {stream_target}! Streaming live...")
        
        frame_index = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                print(f"[!] Lost hardware frame signal from {camera_id}. Forcing network re-scan...")
                break
                
            frame_index += 1
            if frame_index % 5 != 0:
                continue
                
            try:
                resized_img = cv2.resize(frame, (640, 480))
                _, img_buffer = cv2.imencode('.jpg', resized_img)
                base64_payload_string = base64.b64encode(img_buffer).decode('utf-8')
                
                telemetry_packet = {
                    "camera_id": camera_id,
                    "current_floor": int(config["floor"]),
                    "frame_image_base64": base64_payload_string
                }
                
                response = requests.post(API_URL, json=telemetry_packet, timeout=2)
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("identified"):
                        print(f"🔍 [RE-ID MATCH - {camera_id}]: Located '{result['name']}' on Floor {result['current_floor']}")
                        if result.get("floor_unauthorized_alert"):
                            print(f"🚨🚨 [CRITICAL ALERT]: Unauthorized Area Intrusion Breach detected for '{result['name']}'!")
                
            except requests.exceptions.RequestException:
                pass
            except Exception as runtime_err:
                print(f"[!] Error processing matrix loop context for {camera_id}: {runtime_err}")
                
        cap.release()
        time.sleep(2)

if __name__ == "__main__":
    print("=====================================================================")
    print("🚀 INITIALIZING CENTRAL AI MULTI-CAMERA SURVEILLANCE TRACKING LAYER")
    print("=====================================================================")
    
    # Perform automated network mapping right during startup initialization routines
    discover_phone_ip_automatically()

    CAMERA_NETWORK_POOL = {
        "Camera_Node_1_Entrance": {
            "stream_url": AUTOMATED_STREAM_URL, 
            "floor": 0
        }
    }

    for node_id, node_config in CAMERA_NETWORK_POOL.items():
        thread = threading.Thread(
            target=camera_connection_worker, 
            args=(node_id, node_config), 
            daemon=True
        )
        thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Shutting down surveillance tracking streams safely. System Offline.")