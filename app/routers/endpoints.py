from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Header, BackgroundTasks
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app import models, schemas
from app.services import teams_service

router = APIRouter(prefix="/api/endpoints", tags=["Endpoint Monitoring"])


def _check_agent_key(x_agent_key: str = Header(default="")):
    if x_agent_key != settings.AGENT_API_KEY:
        raise HTTPException(401, "Invalid agent API key")


@router.post("/register", response_model=schemas.EndpointOut)
def register_endpoint(payload: schemas.EndpointRegister, db: Session = Depends(get_db), _=Depends(_check_agent_key)):
    customer = db.query(models.Customer).get(payload.customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")

    existing = (
        db.query(models.Endpoint)
        .filter_by(customer_id=payload.customer_id, hostname=payload.hostname)
        .first()
    )
    if existing:
        for k, v in payload.model_dump().items():
            setattr(existing, k, v)
        existing.status = models.EndpointStatus.ONLINE
        existing.last_seen = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    endpoint = models.Endpoint(**payload.model_dump(), status=models.EndpointStatus.ONLINE, last_seen=datetime.utcnow())
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    return endpoint


@router.post("/heartbeat")
async def heartbeat(payload: schemas.EndpointHeartbeat, background_tasks: BackgroundTasks, db: Session = Depends(get_db), _=Depends(_check_agent_key)):
    endpoint = db.query(models.Endpoint).get(payload.endpoint_id)
    if not endpoint:
        raise HTTPException(404, "Endpoint not registered. Call /register first.")

    metric = models.EndpointMetric(
        endpoint_id=endpoint.id,
        cpu_percent=payload.cpu_percent,
        memory_percent=payload.memory_percent,
        disk_percent=payload.disk_percent,
        uptime_seconds=payload.uptime_seconds,
        disk_health_ok=payload.disk_health_ok,
        av_enabled=payload.av_enabled,
        pending_reboot=payload.pending_reboot,
    )
    db.add(metric)

    endpoint.last_seen = datetime.utcnow()
    if payload.ip_address:
        endpoint.ip_address = payload.ip_address

    alerts = []
    if payload.disk_health_ok is False:
        alerts.append("Disk health check FAILED (SMART error)")
    if payload.disk_percent and payload.disk_percent > 90:
        alerts.append(f"Disk usage critical: {payload.disk_percent:.0f}% full")
    if payload.memory_percent and payload.memory_percent > 95:
        alerts.append(f"Memory usage critical: {payload.memory_percent:.0f}%")
    if payload.av_enabled is False:
        alerts.append("Antivirus / endpoint protection is DISABLED")

    endpoint.status = models.EndpointStatus.WARNING if alerts else models.EndpointStatus.ONLINE
    db.commit()

    if alerts:
        background_tasks.add_task(
            _notify_alert, endpoint.id, "; ".join(alerts)
        )

    return {"ok": True, "alerts": alerts}


async def _notify_alert(endpoint_id: str, reason: str):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        endpoint = db.query(models.Endpoint).get(endpoint_id)
        if endpoint:
            await teams_service.notify_endpoint_alert(endpoint.hostname, endpoint.customer.name, reason)
    finally:
        db.close()


@router.get("/", response_model=List[schemas.EndpointOut])
def list_endpoints(db: Session = Depends(get_db)):
    from datetime import timedelta
    threshold = datetime.utcnow() - timedelta(minutes=settings.AGENT_OFFLINE_THRESHOLD_MINUTES)
    endpoints = db.query(models.Endpoint).all()
    for e in endpoints:
        if e.last_seen and e.last_seen < threshold and e.status != models.EndpointStatus.OFFLINE:
            e.status = models.EndpointStatus.OFFLINE
    db.commit()
    return endpoints


@router.get("/{endpoint_id}/metrics")
def endpoint_metrics(endpoint_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(models.EndpointMetric)
        .filter_by(endpoint_id=endpoint_id)
        .order_by(models.EndpointMetric.timestamp.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "timestamp": r.timestamp,
            "cpu_percent": r.cpu_percent,
            "memory_percent": r.memory_percent,
            "disk_percent": r.disk_percent,
            "disk_health_ok": r.disk_health_ok,
        }
        for r in rows
    ]
