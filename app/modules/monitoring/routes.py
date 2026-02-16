"""
Monitoring API routes and dashboard pages
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
import logging

from core.database import get_db
from core.monitoring.metrics import get_metrics, get_metrics_content_type
from core.monitoring.alerts import AlertSeverity, AlertType
from modules.auth.dependencies import get_current_user
from modules.auth.models import User, Role
from modules.monitoring.service import MonitoringService
from modules.monitoring.schemas import (
    AlertResponse, AlertListResponse, AlertCountsResponse,
    HealthCheckResponse, DashboardStats, ResolveAlertRequest,
    LogListResponse
)

logger = logging.getLogger("app")

router = APIRouter(prefix="/monitoring", tags=["📊 Monitoring"])
templates = Jinja2Templates(directory="templates")


def require_admin(user: User = Depends(get_current_user)):
    """Require admin role for monitoring endpoints"""
    if user.role != Role.admin:
        raise HTTPException(
            status_code=403,
            detail="Admin access required"
        )
    return user


# ===================================
# Metrics Endpoint (Prometheus format)
# ===================================
@router.get(
    "/metrics",
    response_class=Response,
    summary="Prometheus Metrics",
    description="Get application metrics in Prometheus format"
)
async def metrics_endpoint():
    """
    Export metrics in Prometheus format
    This endpoint is typically scraped by Prometheus server
    """
    metrics_data = get_metrics()
    return Response(
        content=metrics_data,
        media_type=get_metrics_content_type()
    )


# ===================================
# Alerts API
# ===================================
@router.get(
    "/alerts",
    response_model=AlertListResponse,
    summary="Get Alerts",
    description="Get recent security alerts with optional filtering"
)
async def get_alerts(
    limit: int = Query(default=100, le=1000),
    severity: Optional[AlertSeverity] = None,
    alert_type: Optional[AlertType] = None,
    resolved: Optional[bool] = None,
    hours: Optional[int] = None,
    user: User = Depends(require_admin)
):
    """Get recent alerts with filtering"""
    alerts = await MonitoringService.get_alerts(
        limit=limit,
        severity=severity,
        alert_type=alert_type,
        resolved=resolved,
        hours=hours
    )
    
    alert_responses = [
        AlertResponse(
            id=a.id,
            timestamp=a.timestamp,
            severity=a.severity,
            type=a.type,
            message=a.message,
            user_id=a.user_id,
            ip_address=a.ip_address,
            details=a.details,
            resolved=a.resolved,
            resolved_at=a.resolved_at,
            resolved_by=a.resolved_by
        )
        for a in alerts
    ]
    
    return AlertListResponse(
        alerts=alert_responses,
        total=len(alert_responses),
        page=1,
        per_page=limit
    )


@router.get(
    "/alerts/{alert_id}",
    response_model=AlertResponse,
    summary="Get Alert",
    description="Get specific alert by ID"
)
async def get_alert(
    alert_id: str,
    user: User = Depends(require_admin)
):
    """Get specific alert by ID"""
    alert = await MonitoringService.get_alert_by_id(alert_id)
    
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    return AlertResponse(
        id=alert.id,
        timestamp=alert.timestamp,
        severity=alert.severity,
        type=alert.type,
        message=alert.message,
        user_id=alert.user_id,
        ip_address=alert.ip_address,
        details=alert.details,
        resolved=alert.resolved,
        resolved_at=alert.resolved_at,
        resolved_by=alert.resolved_by
    )


@router.post(
    "/alerts/{alert_id}/resolve",
    summary="Resolve Alert",
    description="Mark an alert as resolved"
)
async def resolve_alert(
    alert_id: str,
    request: ResolveAlertRequest,
    user: User = Depends(require_admin)
):
    """Mark alert as resolved"""
    resolved_by = request.resolved_by or user.id
    
    success = await MonitoringService.resolve_alert(alert_id, resolved_by)
    
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found or already resolved")
    
    return {"status": "success", "message": "Alert resolved"}


@router.get(
    "/alerts/counts",
    response_model=AlertCountsResponse,
    summary="Get Alert Counts",
    description="Get counts of alerts by severity"
)
async def get_alert_counts(user: User = Depends(require_admin)):
    """Get alert counts by severity"""
    return await MonitoringService.get_alert_counts()


# ===================================
# Health Check API
# ===================================
@router.get(
    "/health",
    response_model=HealthCheckResponse,
    summary="Health Check",
    description="Get system health status"
)
async def health_check(
    detailed: bool = Query(default=False, description="Include detailed health checks"),
    user: User = Depends(require_admin)
):
    """Get system health status"""
    health = await MonitoringService.get_system_health(detailed=detailed)
    return health


# ===================================
# Statistics API
# ===================================
@router.get(
    "/stats",
    response_model=DashboardStats,
    summary="Dashboard Statistics",
    description="Get aggregated statistics for monitoring dashboard"
)
async def get_stats(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    """Get dashboard statistics"""
    return await MonitoringService.get_dashboard_stats(db)


# ===================================
# Logs API
# ===================================
@router.get(
    "/logs",
    response_model=LogListResponse,
    summary="Get Logs",
    description="Get recent application logs"
)
async def get_logs(
    limit: int = Query(default=100, le=1000),
    level: Optional[str] = None,
    search: Optional[str] = None,
    user: User = Depends(require_admin)
):
    """Get recent logs"""
    logs = MonitoringService.get_recent_logs(
        limit=limit,
        level=level,
        search=search
    )
    
    return LogListResponse(
        logs=logs,
        total=len(logs),
        page=1,
        per_page=limit
    )


@router.get(
    "/logs/security",
    response_model=LogListResponse,
    summary="Get Security Logs",
    description="Get recent security logs"
)
async def get_security_logs(
    limit: int = Query(default=100, le=1000),
    user: User = Depends(require_admin)
):
    """Get recent security logs"""
    logs = await MonitoringService.get_security_logs(limit=limit)
    
    return LogListResponse(
        logs=logs,
        total=len(logs),
        page=1,
        per_page=limit
    )


# ===================================
# Dashboard Web Pages
# ===================================
@router.get(
    "/dashboard",
    response_class=HTMLResponse,
    summary="Monitoring Dashboard",
    description="Web dashboard for system monitoring",
    include_in_schema=False
)
async def dashboard_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    """Monitoring dashboard page"""
    try:
        # Get dashboard stats
        stats = await MonitoringService.get_dashboard_stats(db)
        
        # Get recent alerts
        recent_alerts = await MonitoringService.get_alerts(limit=10)
        
        # Get health status
        health = await MonitoringService.get_system_health(detailed=True)
        
        return templates.TemplateResponse(
            "monitoring/dashboard.html",
            {
                "request": request,
                "user": user,
                "stats": stats,
                "alerts": recent_alerts,
                "health": health
            }
        )
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}")
        raise HTTPException(status_code=500, detail="Error loading dashboard")


@router.get(
    "/alerts-page",
    response_class=HTMLResponse,
    summary="Alerts Page",
    description="Web page for managing security alerts",
    include_in_schema=False
)
async def alerts_page(
    request: Request,
    page: int = Query(default=1, ge=1),
    severity: Optional[str] = None,
    resolved: Optional[bool] = None,
    user: User = Depends(require_admin)
):
    """Alerts management page"""
    try:
        # Convert severity string to enum
        severity_enum = None
        if severity:
            try:
                severity_enum = AlertSeverity(severity.lower())
            except ValueError:
                pass
        
        # Get alerts
        alerts = await MonitoringService.get_alerts(
            limit=50,
            severity=severity_enum,
            resolved=resolved
        )
        
        # Get counts
        counts = await MonitoringService.get_alert_counts()
        
        return templates.TemplateResponse(
            "monitoring/alerts.html",
            {
                "request": request,
                "user": user,
                "alerts": alerts,
                "counts": counts,
                "current_page": page,
                "severity_filter": severity,
                "resolved_filter": resolved
            }
        )
    except Exception as e:
        logger.error(f"Error loading alerts page: {e}")
        raise HTTPException(status_code=500, detail="Error loading alerts page")
