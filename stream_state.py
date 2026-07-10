# stream_state.py
import threading

_last_frame = None
_frame_lock = threading.Lock()
_streaming_active = False
_current_action = "في انتظار البث"
_current_project = "-"
_current_region = "-"
_cookie_count = 0
_current_token = "-"
_current_email = "-"

def update_frame(frame_bytes):
    global _last_frame
    with _frame_lock:
        _last_frame = frame_bytes

def get_last_frame():
    with _frame_lock:
        return _last_frame

def update_status(action=None, project=None, region=None, cookies=None, token=None, email=None):
    global _current_action, _current_project, _current_region, _cookie_count, _current_token, _current_email
    if action is not None:
        _current_action = action
    if project is not None:
        _current_project = project
    if region is not None:
        _current_region = region
    if cookies is not None:
        _cookie_count = cookies
    if token is not None:
        _current_token = token
    if email is not None:
        _current_email = email

def get_status():
    return {
        "action": _current_action,
        "project": _current_project,
        "region": _current_region,
        "cookies": _cookie_count,
        "token": _current_token,
        "email": _current_email,
        "streaming": _streaming_active
    }

def set_streaming(status: bool):
    global _streaming_active
    _streaming_active = status