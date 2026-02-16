# 📝 Logging System Documentation

## Overview

The Employee Cabinet logging system provides structured JSON logging with PII redaction, security event filtering, and automatic log rotation. All logs are enriched with request context (request_id, user_id, session_id) for distributed tracing.

## Architecture

### Components

1. **Enhanced JSON Formatter** (`app/core/logging/formatters.py`)
   - Structured JSON logs with Moscow timezone
   - Request context (request_id, user_id, session_id, trace_id)
   - Exception tracebacks
   - Module and function information

2. **Sensitive Data Filter** (`app/core/logging/filters.py`)
   - Automatic redaction of passwords, tokens, API keys
   - PII masking (email, phone numbers)
   - Security event detection and routing

3. **Custom Handlers** (`app/core/logging/handlers.py`)
   - SecurityLogHandler - Separate handler for security events
   - RotatingFileHandlerWithCompression - Auto-compress old logs
   - Configurable rotation (10MB per file, 30 days retention)

4. **Access Log Middleware** (`app/core/logging.py`)
   - Log all HTTP requests with metrics
   - User identification from JWT tokens
   - Request/response timing

## Log Structure

### JSON Log Format

```json
{
  "timestamp": "2026-02-16T13:24:55+03:00",
  "time": "2026-02-16 13:24:55",
  "level": "INFO",
  "logger": "app",
  "environment": "development",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": 123,
  "module": "auth",
  "function": "login",
  "line": 42,
  "event": "login_success",
  "email": "u***@example.com",
  "ip": "192.168.1.100"
}
```

### Log Levels

| Level | Usage |
|-------|-------|
| **DEBUG** | Detailed diagnostic information |
| **INFO** | General informational messages |
| **WARNING** | Warning messages (e.g., failed login attempts) |
| **ERROR** | Error messages (e.g., exceptions) |
| **CRITICAL** | Critical system failures |

### Log Categories

1. **Application Logs** (`logs/app.log`)
   - General application events
   - HTTP requests
   - User actions
   - System operations

2. **Security Logs** (`logs/security.log`)
   - Authentication events
   - Authorization failures
   - Security alerts
   - Suspicious activities

3. **Audit Logs** (`logs/audit.log`)
   - User actions requiring audit trail
   - Data modifications
   - Administrative operations

## Configuration

### Logging Configuration in `app/main.py`

```python
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": JsonFormatter,
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        },
        "security": {
            "()": SecurityLogHandler,
            "level": "WARNING",
        },
    },
    "loggers": {
        "app": {
            "handlers": ["default", "database"],
            "level": "DEBUG" if settings.DEBUG else "INFO",
            "propagate": False,
        },
    },
}
```

### Environment Variables

```bash
LOG_RETENTION_DAYS=30
DEBUG=false
ENVIRONMENT=production
```

## Log Filters

### Sensitive Data Redaction

Automatically redacts:
- Passwords: `password=***REDACTED***`
- Tokens: `token=***REDACTED***`
- API Keys: `api_key=***REDACTED***`
- Bearer tokens: `Bearer ***REDACTED***`
- Credit card numbers: `****-****-****-****`

**Example:**

Input:
```python
logger.info({"event": "user_login", "password": "secret123", "token": "abc123xyz"})
```

Output:
```json
{
  "event": "user_login",
  "password": "***REDACTED***",
  "token": "***REDACTED***"
}
```

### PII Masking

Automatically masks:
- Email addresses: `user@example.com` → `u***@example.com`
- Phone numbers: `+1-234-567-8901` → `***-***-8901`

**Example:**

Input:
```python
logger.info({"event": "user_created", "email": "john.doe@example.com", "phone": "+1-234-567-8901"})
```

Output:
```json
{
  "event": "user_created",
  "email": "j***@example.com",
  "phone": "***-***-8901"
}
```

### Security Event Filtering

Security events are automatically routed to `logs/security.log`:
- `security_alert`
- `brute_force`
- `failed_login`
- `unauthorized_access`
- `privilege_escalation`
- `sql_injection`
- `xss_attempt`

## Usage Examples

### Basic Logging

```python
import logging

logger = logging.getLogger("app")

logger.info("Application started")
logger.warning("Disk space low")
logger.error("Failed to connect to database", exc_info=True)
```

### Structured Logging

```python
logger.info({
    "event": "user_login",
    "user_id": 123,
    "email": "user@example.com",
    "ip": "192.168.1.100",
    "success": True
})
```

### Logging with Request Context

Request context is automatically added by middleware:

```python
# In a route handler
logger.info({
    "event": "document_uploaded",
    "document_id": 456,
    "filename": "report.pdf"
})
# Automatically includes: request_id, user_id, session_id
```

### Security Event Logging

```python
logger.warning({
    "event": "failed_login",
    "email": "attacker@example.com",
    "ip": "10.0.0.1",
    "attempts": 5
})
# Automatically routed to security.log
```

### Exception Logging

```python
try:
    risky_operation()
except Exception as e:
    logger.error({
        "event": "operation_failed",
        "error": str(e)
    }, exc_info=True)
```

## Log Rotation

### Configuration

- **Max File Size**: 10 MB
- **Backup Count**: 30 files
- **Compression**: Automatic (gzip)
- **Retention**: 30 days

### Rotation Behavior

1. When log file reaches 10 MB:
   - Current file renamed to `app.log.1`
   - New `app.log` file created
   - Old `app.log.1` compressed to `app.log.1.gz`

2. Older files shifted:
   - `app.log.1.gz` → `app.log.2.gz`
   - `app.log.2.gz` → `app.log.3.gz`
   - etc.

3. Files older than 30 backups are deleted

### Manual Rotation

```bash
# Force log rotation
kill -HUP $(cat /var/run/app.pid)
```

## Log Analysis

### Reading Logs

#### Using `jq` (JSON processor)

```bash
# Get all error logs
cat logs/app.log | jq 'select(.level == "ERROR")'

# Get logs for specific user
cat logs/app.log | jq 'select(.user_id == 123)'

# Get logs with specific event
cat logs/app.log | jq 'select(.event == "login_success")'

# Count events by type
cat logs/app.log | jq -r '.event' | sort | uniq -c
```

#### Using `grep`

```bash
# Find logs with keyword
grep "failed_login" logs/security.log

# Find logs from specific IP
grep "192.168.1.100" logs/app.log

# Find errors in last hour
find logs/ -name "app.log" -mmin -60 -exec grep "ERROR" {} \;
```

### Log Aggregation

#### With Elasticsearch + Kibana (ELK)

1. **Filebeat Configuration** (`filebeat.yml`):

```yaml
filebeat.inputs:
  - type: log
    enabled: true
    paths:
      - /app/logs/*.log
    json.keys_under_root: true
    json.add_error_key: true

output.elasticsearch:
  hosts: ["elasticsearch:9200"]
  index: "employee-cabinet-%{+yyyy.MM.dd}"
```

2. **Kibana Visualizations**:
   - Log volume over time
   - Top error messages
   - Failed login attempts by IP
   - User activity timeline

#### With Loki + Grafana

1. **Promtail Configuration** (`promtail.yml`):

```yaml
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: employee_cabinet
    static_configs:
      - targets:
          - localhost
        labels:
          job: employee_cabinet
          __path__: /app/logs/*.log
```

2. **Grafana Queries**:

```logql
# All error logs
{job="employee_cabinet"} |= "ERROR"

# Failed logins
{job="employee_cabinet"} | json | event="failed_login"

# Logs for specific user
{job="employee_cabinet"} | json | user_id="123"
```

## Monitoring Logs

### Prometheus Metrics from Logs

Use Loki with LogQL or mtail to extract metrics:

```logql
# Count of errors per minute
count_over_time({job="employee_cabinet"} |= "ERROR" [1m])

# Failed login rate
rate({job="employee_cabinet"} | json | event="failed_login" [5m])
```

### Alerting on Log Patterns

#### With Loki

Create alert rule in Prometheus:

```yaml
groups:
  - name: logs
    rules:
      - alert: HighErrorRate
        expr: |
          rate({job="employee_cabinet"} |= "ERROR" [5m]) > 0.1
        annotations:
          summary: "High error rate detected"
```

#### With Elasticsearch Watcher

```json
{
  "trigger": {
    "schedule": {"interval": "5m"}
  },
  "input": {
    "search": {
      "request": {
        "indices": ["employee-cabinet-*"],
        "body": {
          "query": {
            "bool": {
              "must": [
                {"term": {"level": "ERROR"}},
                {"range": {"@timestamp": {"gte": "now-5m"}}}
              ]
            }
          }
        }
      }
    }
  },
  "condition": {
    "compare": {"ctx.payload.hits.total": {"gt": 10}}
  },
  "actions": {
    "email_admin": {
      "email": {
        "to": "admin@example.com",
        "subject": "High error rate",
        "body": "Detected {{ctx.payload.hits.total}} errors"
      }
    }
  }
}
```

## Best Practices

### 1. Use Structured Logging

**Good:**
```python
logger.info({
    "event": "user_created",
    "user_id": user.id,
    "email": user.email
})
```

**Bad:**
```python
logger.info(f"User {user.email} created with ID {user.id}")
```

### 2. Include Context

Always include relevant context:
- `event`: Type of event
- `user_id`: User performing action
- `ip`: Client IP address
- `resource_id`: ID of affected resource

### 3. Choose Appropriate Log Level

- **DEBUG**: Verbose information for debugging
- **INFO**: Normal operation events
- **WARNING**: Potential issues (e.g., retries)
- **ERROR**: Errors that need attention
- **CRITICAL**: System failures

### 4. Don't Log Sensitive Data

Filters will redact common patterns, but avoid logging:
- Raw passwords
- Full credit card numbers
- Social security numbers
- API keys/secrets
- Session tokens

### 5. Use Correlation IDs

Request IDs are automatically added by middleware. Use them for tracing:

```python
logger.info({
    "event": "processing_started",
    "request_id": request_id
})
# ... later ...
logger.info({
    "event": "processing_completed",
    "request_id": request_id
})
```

### 6. Log Exceptions Properly

```python
try:
    operation()
except Exception as e:
    logger.error({
        "event": "operation_failed",
        "error": str(e),
        "error_type": type(e).__name__
    }, exc_info=True)  # Include traceback
```

### 7. Monitor Log Volume

- Set up alerts for abnormal log volume
- Monitor disk usage
- Ensure log rotation is working

## Troubleshooting

### Logs Not Appearing

1. Check log level: `DEBUG` vs `INFO`
2. Verify log directory exists and is writable
3. Check `LOGGING_CONFIG` in `main.py`
4. Verify handlers are configured correctly

### Logs Not Rotating

1. Check file permissions on log directory
2. Verify `maxBytes` and `backupCount` settings
3. Check disk space
4. Review handler configuration

### PII Still Visible in Logs

1. Verify filters are configured:
   ```python
   from core.logging.filters import get_logger
   logger = get_logger("app", enable_pii_masking=True)
   ```
2. Check filter patterns in `filters.py`
3. Add custom patterns if needed

### Poor Log Performance

1. Reduce log level in production (INFO instead of DEBUG)
2. Use asynchronous logging handlers
3. Implement log sampling for high-volume events
4. Consider structured logging aggregators

## References

- [Python Logging Documentation](https://docs.python.org/3/library/logging.html)
- [Elasticsearch Documentation](https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html)
- [Grafana Loki Documentation](https://grafana.com/docs/loki/latest/)
- [jq Manual](https://stedolan.github.io/jq/manual/)
