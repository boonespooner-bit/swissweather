import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = 2
timeout = 120
preload_app = True

_scheduler_started = False


def post_fork(server, worker):
    global _scheduler_started
    if not _scheduler_started:
        _scheduler_started = True
        from app import _start_scheduler
        _start_scheduler()
        from weather import trigger_background_fetch
        trigger_background_fetch()
