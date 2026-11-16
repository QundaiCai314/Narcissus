"""Short-lived, owner-scoped contents previews; no database or object writes."""
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from .pdf_outline import preview

_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='contents-preview')
_slot=threading.BoundedSemaphore(1)
_lock=threading.Lock()
_jobs={}


def start(data,pages,owner,notebook):
    if not _slot.acquire(blocking=False):raise RuntimeError('目录识别正在进行，请完成后再试')
    ident=str(uuid.uuid4());now=time.monotonic()
    with _lock:
        for key in list(_jobs):
            if now-_jobs[key]['created']>1200:del _jobs[key]
        _jobs[ident]=dict(owner=owner,notebook=notebook,created=now,status='running',completed_pages=0,total_pages=0)
    def progress(completed,total):
        with _lock:_jobs[ident].update(completed_pages=completed,total_pages=total)
    def work():
        try:
            result=preview(data,pages,progress=progress)
            with _lock:_jobs[ident].update(status='done',result=result,completed_pages=len(result['ocr_pages']))
        except ValueError as exc:
            with _lock:_jobs[ident].update(status='error',error=str(exc))
        except Exception:
            with _lock:_jobs[ident].update(status='error',error='目录无法可靠读取，请核对PDF和目录页码')
        finally:_slot.release()
    try:_pool.submit(work)
    except Exception:
        with _lock:del _jobs[ident]
        _slot.release();raise
    return dict(job_id=ident,status='running')


def lookup(ident,owner,notebook):
    with _lock:
        job=_jobs.get(ident)
        if not job or job['owner']!=owner or job['notebook']!=notebook or time.monotonic()-job['created']>1200:return None
        return {k:v for k,v in job.items() if k not in ('owner','notebook','created')}
