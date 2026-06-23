import cv2
import mediapipe as mp
import serial
import json
import time
import os
import threading
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# ==============================================================================
# CONFIGURATION
# ==============================================================================
SERIAL_PORT = 'COM4' 
BAUD_RATE = 115200

# 1 is usually the USB Webcam. 0 is usually the built-in laptop camera.
CAMERA_INDEX = 1

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(SCRIPT_DIR, 'face_landmarker.task')
SENSITIVITY_THRESHOLD = 0.02 

# Maximum times per second to send data to the Pico (Prevents USB buffer overflow)
MAX_SEND_FPS = 10

# ==============================================================================
# BACKGROUND WEBCAM THREAD (Prevents Buffer Freezes)
# ==============================================================================
class WebcamStream:
    def __init__(self, src=0):
        self.stream = cv2.VideoCapture(src)
        self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        (self.grabbed, self.frame) = self.stream.read()
        if self.grabbed:
            self.frame = cv2.resize(self.frame, (640, 480))
        self.stopped = False

    def start(self):
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True
        self.thread.start()
        return self

    def update(self):
        while not self.stopped:
            grabbed, frame = self.stream.read()
            if grabbed:
                self.frame = cv2.resize(frame, (640, 480))
            self.grabbed = grabbed

    def read(self):
        return self.grabbed, self.frame

    def stop(self):
        self.stopped = True
        if hasattr(self, 'thread'):
            self.thread.join()
        self.stream.release()

# ==============================================================================
# MAIN PIPELINE
# ==============================================================================
def main():
    print("=========================================")
    print("1. CONNECTING TO PICO...")
    print("=========================================")
    pico = None
    try:
        # CRITICAL FIX: Increased write_timeout slightly for stability
        pico = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0, write_timeout=0.05)
        
        # CRITICAL FIX: Assert DTR/RTS so MicroPython knows the PC is awake
        pico.dtr = True
        pico.rts = True
        
        print(f"[SUCCESS] Connected to Pico on {SERIAL_PORT}")

        # ---> ADD THESE TWO LINES <---
        print("Waiting 2 seconds for robot to wake up...")
        time.sleep(2.0) 
        # -----------------------------

    except Exception as e:
        print(f"[WARNING] Could not connect to {SERIAL_PORT}. Is it plugged in?")
        print("Continuing in Visual-Only mode...")

    print("\n=========================================")
    print("2. LOADING AI ENGINE...")
    print("=========================================")
    try:
        base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.IMAGE, 
            output_face_blendshapes=True,
            num_faces=1)
        detector = vision.FaceLandmarker.create_from_options(options)
        print("[SUCCESS] MediaPipe Loaded.")
    except Exception as e:
        print(f"\n[ERROR] Failed to load AI: {e}")
        return

    print("\n=========================================")
    print(f"3. STARTING WEBCAM THREAD ON INDEX {CAMERA_INDEX}...")
    print("=========================================")
    
    vs = WebcamStream(src=CAMERA_INDEX).start()
    
    if not vs.grabbed:
        print(f"\n[ERROR] Could not open Webcam {CAMERA_INDEX}.")
        vs.stop()
        return

    print("[READY] Press 'ESC' on the video window to quit.")

    prev_frame_time = 0
    last_send_time = 0
    min_send_interval = 1.0 / MAX_SEND_FPS

    while True:
        success, frame = vs.read()
        if not success:
            continue

        current_time = time.time()
        fps = 1 / (current_time - prev_frame_time) if prev_frame_time > 0 else 0
        prev_frame_time = current_time

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        detection_result = detector.detect(mp_image)

        if detection_result.face_blendshapes:
            blendshapes = detection_result.face_blendshapes[0]
            
            payload = {}
            for shape in blendshapes:
                if shape.category_name == "_neutral":
                    continue
                if shape.score > SENSITIVITY_THRESHOLD:
                    payload[shape.category_name] = round(shape.score, 3)

            # RATE LIMITER: Only send data 15 times a second to save the Pico!
            if pico and payload and (current_time - last_send_time > min_send_interval):
                json_string = json.dumps(payload) + '\n'
                try:
                    pico.write(json_string.encode('utf-8'))
                    last_send_time = current_time
                except serial.SerialTimeoutException:
                    cv2.putText(frame, "USB BLOCKED!", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                except Exception as e:
                    pass

            # Draw visual debug info
            active = sorted(payload.items(), key=lambda item: item[1], reverse=True)[:3]
            debug_text = " | ".join([f"{k}: {v:.2f}" for k, v in active])
            cv2.putText(frame, debug_text, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, "TRACKING", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
        cv2.putText(frame, f"FPS: {int(fps)}", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
        cv2.imshow('Animatronic Mocap Studio', frame)

        if cv2.waitKey(1) & 0xFF == 27:
            break

    vs.stop()
    cv2.destroyAllWindows()
    if pico:
        pico.close()

if __name__ == '__main__':
    main()