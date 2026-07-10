import time
from threading import Lock

_last_frame = None
_streaming = False
_status = {"project": "-", "streaming": False, "duration": "00:00:00"}
_lock = Lock()
_start_time = None

def update_frame(frame_data):
    global _last_frame
    with _lock:
        _last_frame = frame_data

def get_last_frame():
    with _lock:
        return _last_frame

def set_streaming(status):
    global _streaming, _start_time
    with _lock:
        _streaming = status
        if status:
            _start_time = time.time()
        else:
            _start_time = None
        _status["streaming"] = status

def update_status(**kwargs):
    global _status
    with _lock:
        for key, value in kwargs.items():
            _status[key] = value
        if _start_time:
            elapsed = int(time.time() - _start_time)
            _status["duration"] = f"{elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d}"

def get_status():
    with _lock:
        s = _status.copy()
        if _start_time:
            elapsed = int(time.time() - _start_time)
            s["duration"] = f"{elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d}"
        return s