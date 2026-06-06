import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = 2
preload_app = True


def on_starting(server):
    from app import _start_scheduler
    _start_scheduler()
