from celery import Celery

celery_app = Celery(
    "tasks",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0"
)

@celery_app.task
def create_access_log_task(log_text):
    from database import SessionLocal
    from models import AccessLog
    
    db = SessionLocal()
    new_log = AccessLog(text=log_text)
    db.add(new_log)
    db.commit()
    db.close()
