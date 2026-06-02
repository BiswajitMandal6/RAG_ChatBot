from celery import Celery
from config import REDIS_URL

celery_app = Celery(
    "rag_crawler",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["crawler_tasks"],
)

celery_app.conf.update(
    # Task settings
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,

    # Job retention — keep results for 24 hours
    result_expires=86400,

    # One crawl job at a time per worker (crawling is heavy)
    worker_concurrency=1,
    worker_prefetch_multiplier=1,

    # Retry settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # Rate limiting — max 10 crawl jobs per minute
    task_default_rate_limit="10/m",
)