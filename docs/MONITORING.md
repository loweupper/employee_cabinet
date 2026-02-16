# 📊 Monitoring System Documentation

## Overview

The Employee Cabinet monitoring system provides comprehensive real-time monitoring, security alerting, and metrics collection. It includes Prometheus-compatible metrics, security anomaly detection, health checks, and a web dashboard for visualization.

## Architecture

### Components

1. **Metrics Collection** (`app/core/monitoring/metrics.py`)
   - Prometheus-compatible metrics using `prometheus_client`
   - HTTP request metrics (latency, count, status codes)
   - Authentication metrics (success/failure rates)
   - File upload metrics
   - Security event counters
   - Database connection tracking

2. **Alert System** (`app/core/monitoring/alerts.py`)
   - In-memory alert storage (last 1000 alerts or 24 hours)
   - Four severity levels: LOW, MEDIUM, HIGH, CRITICAL
   - Alert types: brute force, SQL injection, XSS, privilege escalation, etc.
   - Alert resolution tracking

3. **Security Detector** (`app/core/monitoring/detector.py`)
   - Login attempt tracking with Redis
   - Brute force detection (5 failed attempts in 5 minutes)
   - New IP address detection (30-day history)
   - Automatic alert generation on threshold violations

4. **Health Checks** (`app/core/monitoring/health.py`)
   - Database connectivity and latency
   - Redis connectivity and latency
   - Disk space monitoring (10% free threshold)
   - Memory usage monitoring (20% available threshold)
   - System metrics (CPU, load average, uptime)

5. **Notification System**
   - Email notifications for HIGH/CRITICAL alerts (`app/core/notifications/email_notifier.py`)
   - Telegram notifications with inline buttons (`app/core/notifications/telegram_notifier.py`)
   - Rate limiting to prevent notification spam

## Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# Monitoring
MONITORING_ENABLED=true
METRICS_ENABLED=true
ALERT_EMAIL_RECIPIENTS=["admin@example.com","security@example.com"]
LOG_RETENTION_DAYS=30
ALERT_RETENTION_HOURS=24

# Telegram Alerts (optional)
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Alert Thresholds
BRUTE_FORCE_THRESHOLD=5
BRUTE_FORCE_WINDOW_MINUTES=5
```

### Configuration in `app/core/config.py`

```python
class Settings(BaseSettings):
    MONITORING_ENABLED: bool = True
    METRICS_ENABLED: bool = True
    ALERT_EMAIL_RECIPIENTS: List[str] = []
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    LOG_RETENTION_DAYS: int = 30
    ALERT_RETENTION_HOURS: int = 24
    BRUTE_FORCE_THRESHOLD: int = 5
    BRUTE_FORCE_WINDOW_MINUTES: int = 5
```

## API Endpoints

All monitoring endpoints require admin authentication.

### Metrics

**GET** `/api/v1/monitoring/metrics`
- Returns Prometheus metrics in text format
- Used by Prometheus scraper
- No authentication required for scraping

### Alerts

**GET** `/api/v1/monitoring/alerts`
- List recent alerts with filtering
- Query parameters:
  - `limit` (default: 100, max: 1000)
  - `severity` (low, medium, high, critical)
  - `alert_type` (e.g., brute_force_attempt)
  - `resolved` (true/false)
  - `hours` (time window)

**GET** `/api/v1/monitoring/alerts/{alert_id}`
- Get specific alert details

**POST** `/api/v1/monitoring/alerts/{alert_id}/resolve`
- Mark alert as resolved
- Body: `{"resolved_by": <user_id>}` (optional)

**GET** `/api/v1/monitoring/alerts/counts`
- Get alert counts by severity

### Health Check

**GET** `/health`
- Basic health check
- Query parameter: `detailed=true` for comprehensive checks

**GET** `/api/v1/monitoring/health`
- Comprehensive health status
- Requires authentication
- Query parameter: `detailed=true`

### Dashboard

**GET** `/api/v1/monitoring/dashboard`
- Web dashboard (HTML)
- Real-time metrics and alerts
- Auto-refreshes every 30 seconds

**GET** `/api/v1/monitoring/alerts-page`
- Alerts management page (HTML)
- Filter and resolve alerts

### Statistics

**GET** `/api/v1/monitoring/stats`
- Aggregated dashboard statistics
- Active sessions, failed logins, alert counts

### Logs

**GET** `/api/v1/monitoring/logs`
- Recent application logs
- Query parameters:
  - `limit` (default: 100, max: 1000)
  - `level` (DEBUG, INFO, WARNING, ERROR)
  - `search` (text search)

**GET** `/api/v1/monitoring/logs/security`
- Recent security logs

## Alert Types

| Alert Type | Severity | Description |
|------------|----------|-------------|
| `multiple_failed_logins` | HIGH | 5+ failed login attempts in 5 minutes |
| `brute_force_attempt` | HIGH | Rapid authentication attempts from single IP |
| `new_ip_login` | MEDIUM | User logged in from previously unseen IP |
| `suspicious_file_upload` | HIGH | Upload with dangerous extension |
| `sql_injection_attempt` | CRITICAL | Detected SQL injection pattern |
| `xss_attempt` | HIGH | Detected XSS pattern |
| `privilege_escalation` | CRITICAL | Unauthorized access attempt |
| `account_lockout` | MEDIUM | Account locked due to failed attempts |

## Metrics Collected

### HTTP Metrics
- `http_requests_total{method, endpoint, status_code}` - Counter
- `http_request_duration_seconds{method, endpoint}` - Histogram

### Authentication Metrics
- `auth_attempts_total{result, email}` - Counter
- `auth_failures_total{email}` - Counter

### Session Metrics
- `active_sessions_count` - Gauge

### File Upload Metrics
- `file_uploads_total{file_type, result}` - Counter

### Security Metrics
- `security_events_total{event_type}` - Counter

### Database Metrics
- `database_connections` - Gauge
- `database_query_duration_seconds` - Histogram

## Integration with External Tools

### Prometheus

1. Configure Prometheus to scrape metrics:

```yaml
scrape_configs:
  - job_name: 'employee_cabinet'
    static_configs:
      - targets: ['app:8001']
    metrics_path: '/api/v1/monitoring/metrics'
    scrape_interval: 15s
```

2. Access metrics at: `http://localhost:8001/api/v1/monitoring/metrics`

### Grafana

1. Add Prometheus as data source
2. Import dashboard or create custom visualizations
3. Recommended panels:
   - Request rate and latency (from `http_requests_total`, `http_request_duration_seconds`)
   - Authentication success/failure rate
   - Active sessions
   - Alert counts by severity
   - System health status

### ELK Stack (Elasticsearch, Logstash, Kibana)

1. Configure Logstash to read JSON logs from `logs/app.log`
2. Forward to Elasticsearch
3. Create Kibana dashboards for log analysis

Example Logstash configuration:

```ruby
input {
  file {
    path => "/app/logs/app.log"
    codec => "json"
    type => "app_logs"
  }
  file {
    path => "/app/logs/security.log"
    codec => "json"
    type => "security_logs"
  }
}

output {
  elasticsearch {
    hosts => ["elasticsearch:9200"]
    index => "employee-cabinet-%{+YYYY.MM.dd}"
  }
}
```

### Telegram Bot Setup

1. Create a bot with [@BotFather](https://t.me/botfather)
2. Get bot token
3. Get chat ID:
   ```bash
   # Send a message to your bot, then:
   curl https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
4. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=your_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   ```

## Security Detector Usage

### Recording Login Attempts

Login attempts are automatically recorded in the login endpoint:

```python
from core.monitoring.detector import get_login_tracker

tracker = get_login_tracker()
await tracker.record_attempt(email, ip_address, success=True, user_id=123)
```

### Checking for Brute Force

```python
is_brute_force = await tracker.check_brute_force(ip_address)
if is_brute_force:
    # Block or alert
    pass
```

### Checking Suspicious Activity

```python
activity = await tracker.check_suspicious_activity(email, ip_address)
# Returns: {
#   "brute_force": False,
#   "multiple_failed_logins": False,
#   "new_ip": True,
#   "ip_failed_attempts": 2,
#   "user_failed_attempts": 1
# }
```

## Creating Custom Alerts

```python
from core.monitoring.alerts import create_alert, AlertSeverity, AlertType

await create_alert(
    severity=AlertSeverity.HIGH,
    alert_type=AlertType.SUSPICIOUS_FILE_UPLOAD,
    message="User uploaded .exe file",
    user_id=123,
    ip_address="192.168.1.100",
    details={
        "filename": "malware.exe",
        "size_bytes": 1024000
    }
)
```

## Dashboard Usage

1. Navigate to `/api/v1/monitoring/dashboard`
2. View real-time metrics:
   - System health status
   - Active sessions
   - Failed login attempts (last hour)
   - Unresolved alerts
3. Dashboard auto-refreshes every 30 seconds
4. Click "View All" to see detailed alerts

## Alert Management

1. Navigate to `/api/v1/monitoring/alerts-page`
2. Filter alerts by:
   - Severity (critical, high, medium, low)
   - Status (resolved/unresolved)
3. Mark alerts as resolved with "Mark Resolved" button
4. View alert details (IP address, user ID, timestamp, details)

## Troubleshooting

### Metrics Not Appearing

1. Check `METRICS_ENABLED=true` in `.env`
2. Verify endpoint is accessible: `curl http://localhost:8001/api/v1/monitoring/metrics`
3. Check logs for errors

### Alerts Not Generated

1. Check `MONITORING_ENABLED=true` in `.env`
2. Verify Redis is running and accessible
3. Check LoginAttemptTracker initialization in logs
4. Test alert creation manually

### Email Notifications Not Sending

1. Verify SMTP settings in `.env`
2. Check `ALERT_EMAIL_RECIPIENTS` is a valid JSON array
3. Test SMTP connectivity:
   ```python
   from core.notifications.email_notifier import get_email_notifier
   notifier = get_email_notifier()
   # Check logs for connection errors
   ```

### Telegram Notifications Not Sending

1. Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
2. Test bot connection:
   ```bash
   curl https://api.telegram.org/bot<TOKEN>/getMe
   ```
3. Ensure bot has been started by user (send `/start` to bot)

### Dashboard Not Loading

1. Verify user has admin role
2. Check templates directory exists at `/app/templates/monitoring/`
3. Check browser console for JavaScript errors
4. Verify all monitoring routes are registered

## Performance Considerations

- **Metrics Collection**: Overhead is < 1ms per request
- **Alert Storage**: In-memory storage limited to 1000 alerts
- **Redis Usage**: Login attempts stored with TTL (expires automatically)
- **Log Files**: Rotated at 10MB, compressed automatically
- **Health Checks**: Cached for 5 seconds to avoid excessive DB queries

## Best Practices

1. **Monitor Regularly**: Check dashboard daily for security events
2. **Review Alerts**: Investigate HIGH and CRITICAL alerts immediately
3. **Set Up External Monitoring**: Use Prometheus + Grafana for production
4. **Configure Notifications**: Set up email/Telegram for critical alerts
5. **Rotate Logs**: Ensure log retention policy matches compliance requirements
6. **Test Alerts**: Periodically test alert generation and notification delivery
7. **Update Thresholds**: Adjust `BRUTE_FORCE_THRESHOLD` based on your environment

## References

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [python-telegram-bot Documentation](https://python-telegram-bot.readthedocs.io/)
