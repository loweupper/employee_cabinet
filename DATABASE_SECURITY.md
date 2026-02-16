# Database Security Documentation

This document outlines the security measures implemented in the Employee Cabinet application to protect sensitive data and ensure secure database operations.

## Table of Contents

1. [SQL Injection Prevention](#sql-injection-prevention)
2. [Password Hashing](#password-hashing)
3. [Data Encryption](#data-encryption)
4. [Audit Logging](#audit-logging)
5. [Connection Pool Security](#connection-pool-security)
6. [Backup and Recovery](#backup-and-recovery)
7. [Best Practices](#best-practices)

---

## 1. SQL Injection Prevention

### Implementation

The application uses **SQLAlchemy ORM** exclusively for all database operations, which provides automatic protection against SQL injection attacks.

### How It Works

- All database queries use parameterized statements through SQLAlchemy
- User input is never directly concatenated into SQL queries
- The ORM automatically escapes and sanitizes input data

### Example

```python
# ✅ SAFE - Using SQLAlchemy ORM
user = db.query(User).filter(User.email == user_email).first()

# ❌ UNSAFE - Never do this
# db.execute(f"SELECT * FROM users WHERE email = '{user_email}'")
```

### Guidelines

- **Always** use SQLAlchemy ORM methods for queries
- **Never** use raw SQL with string interpolation
- If raw SQL is absolutely necessary, use parameterized queries with `text()` and bound parameters

---

## 2. Password Hashing

### Implementation

Passwords are hashed using **bcrypt** with a minimum of 12 salt rounds.

### Locations

- `app/modules/auth/utils.py` - Primary password hashing functions
- `app/modules/auth/password.py` - Enhanced password utilities with validation

### Functions

```python
from app.modules.auth.password import hash_password, verify_password

# Hash a password (12 rounds by default)
hashed = hash_password("user_password")

# Verify a password
is_valid = verify_password("user_password", hashed)
```

### Password Requirements

Enforced through `validate_password_strength()`:

- Minimum 8 characters
- At least one uppercase letter (A-Z)
- At least one lowercase letter (a-z)
- At least one digit (0-9)
- At least one special character (!@#$%^&*(),.?":{}|<>)
- Not a common/weak password

### Security Features

- **Salt Rounds**: Configurable (default: 12, recommended: 12-14)
- **Automatic Salting**: Each password gets a unique salt
- **Constant-Time Comparison**: Uses bcrypt's built-in verification to prevent timing attacks
- **No Password Storage**: Only hashed values are stored in the database

---

## 3. Data Encryption

### Implementation

Sensitive data can be encrypted using **Fernet** symmetric encryption (AES-128 in CBC mode).

### Location

`app/core/encryption.py`

### Usage

```python
from app.core.encryption import encrypt_data, decrypt_data

# Encrypt sensitive data
encrypted = encrypt_data("sensitive information")

# Decrypt data
original = decrypt_data(encrypted)

# Check if data is encrypted
from app.core.encryption import is_encrypted
if is_encrypted(data):
    data = decrypt_data(data)
```

### Key Management

- Encryption key is derived from `SECRET_KEY` in settings
- Uses SHA-256 to derive a stable 32-byte key
- Key is base64-encoded for Fernet compatibility

### When to Use Encryption

Encrypt the following types of data:

- Social security numbers
- Banking information
- Personal identification numbers
- Sensitive personal information (PII)
- API keys and credentials stored in the database

### What NOT to Encrypt

- Passwords (use bcrypt hashing instead)
- Data needed for searching/indexing
- Non-sensitive reference data

---

## 4. Audit Logging

### Implementation

All significant database operations are logged for security auditing and compliance.

### Location

`app/core/audit.py`

### Usage

```python
from app.core.audit import log_audit_event, log_login_event

# Log a database operation
await log_audit_event(
    user_id=123,
    action="UPDATE",
    table_name="users",
    record_id=456,
    changes={"email": {"old": "old@example.com", "new": "new@example.com"}},
    ip_address="192.168.1.100"
)

# Log authentication events
await log_login_event(
    user_id=123,
    ip_address="192.168.1.100",
    success=True
)
```

### Logged Information

- **Timestamp**: ISO 8601 format in UTC
- **User ID**: Who performed the action
- **Action**: Type of operation (CREATE, UPDATE, DELETE, READ, LOGIN, etc.)
- **Table Name**: Which table was affected
- **Record ID**: Specific record affected
- **Changes**: Before/after values for updates
- **IP Address**: Origin of the request
- **Additional Info**: Context-specific data

### Audit Log Location

- Primary: `/var/log/employee_cabinet/audit.log`
- Fallback: `./audit.log` (if no permissions for /var/log)
- Format: JSON lines (one JSON object per line)

### Actions to Audit

Critical operations that should be audited:

- User authentication (login/logout)
- Password changes
- Permission/role changes
- Data modifications on sensitive tables
- Administrative actions
- Failed authentication attempts
- Access to sensitive data

---

## 5. Connection Pool Security

### Implementation

SQLAlchemy connection pool is configured with security best practices.

### Location

`app/core/database.py`

### Configuration

```python
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,           # Constant pool of 10 connections
    max_overflow=20,        # Up to 20 additional connections during peak load
    pool_pre_ping=True,     # Verify connections before use
    pool_recycle=3600       # Recycle connections every hour (security)
)
```

### Security Benefits

- **pool_pre_ping=True**: Prevents using stale connections, improves reliability
- **pool_size=10**: Limits base connections to prevent resource exhaustion
- **max_overflow=20**: Caps total connections to prevent DoS attacks
- **pool_recycle=3600**: Refreshes connections hourly to prevent:
  - Stale authentication tokens
  - Connection hijacking
  - Memory leaks in long-lived connections

### Connection Timeout

All connections have a 5-second timeout to prevent hanging connections.

---

## 6. Backup and Recovery

### Recommendations

#### Daily Backups

```bash
# Automated PostgreSQL backup
pg_dump -h localhost -U postgres -d employee_cabinet -F c -f backup_$(date +%Y%m%d).dump
```

#### Backup Schedule

- **Full Backup**: Daily at 2 AM
- **Transaction Logs**: Continuous archiving
- **Retention**: Keep 30 days of daily backups
- **Off-site Storage**: Replicate to secure cloud storage

#### Encryption of Backups

```bash
# Encrypt backup with GPG
pg_dump ... | gpg --encrypt --recipient admin@company.com > backup.dump.gpg
```

#### Recovery Testing

- Test backup restoration monthly
- Document recovery procedures
- Maintain recovery time objective (RTO) < 1 hour
- Maintain recovery point objective (RPO) < 1 hour

### Disaster Recovery Plan

1. **Incident Detection**: Monitor logs and alerts
2. **Isolation**: Disconnect affected systems
3. **Assessment**: Determine scope of data loss
4. **Restoration**: Restore from most recent clean backup
5. **Verification**: Validate data integrity
6. **Post-Mortem**: Document incident and improve procedures

---

## 7. Best Practices

### Development

- ✅ Always use SQLAlchemy ORM
- ✅ Never commit `.env` files or credentials
- ✅ Use environment variables for sensitive configuration
- ✅ Validate and sanitize all user input
- ✅ Use type hints for better code safety
- ✅ Keep dependencies updated (security patches)

### Authentication

- ✅ Enforce strong password requirements
- ✅ Implement rate limiting on login endpoints
- ✅ Use multi-factor authentication (MFA) where possible
- ✅ Lock accounts after repeated failed attempts
- ✅ Log all authentication events

### Database Operations

- ✅ Use transactions for multi-step operations
- ✅ Implement proper error handling
- ✅ Validate data before writing to database
- ✅ Use database constraints (NOT NULL, UNIQUE, FOREIGN KEY)
- ✅ Regularly update statistics and vacuum tables

### Production Deployment

- ✅ Set `DEBUG=false` in production
- ✅ Use strong `SECRET_KEY` (64+ characters)
- ✅ Disable or restrict API documentation (`/docs`)
- ✅ Use HTTPS/TLS for all connections
- ✅ Enable database SSL connections
- ✅ Implement firewall rules (only allow necessary ports)
- ✅ Regular security audits and penetration testing

### Monitoring

- ✅ Monitor failed login attempts
- ✅ Alert on unusual database activity
- ✅ Track query performance and slow queries
- ✅ Monitor connection pool utilization
- ✅ Set up automated backups with verification
- ✅ Regular review of audit logs

### Access Control

- ✅ Principle of least privilege
- ✅ Separate read-only and read-write database users
- ✅ Use different credentials for different environments
- ✅ Regular access review and cleanup
- ✅ Revoke access immediately when no longer needed

---

## Environment Variables

Required security-related environment variables:

```bash
# Strong secret key (min 64 chars in production)
SECRET_KEY=your-cryptographically-random-secret-key

# Database credentials
POSTGRES_PASSWORD=strong-database-password

# Enable audit logging
AUDIT_LOGGING_ENABLED=true

# Connection pool settings (already configured in code)
# No env vars needed - using secure defaults

# Encryption is enabled by default using SECRET_KEY
```

---

## Security Checklist

### Before Production Deployment

- [ ] All passwords hashed with bcrypt (12+ rounds)
- [ ] Sensitive data encrypted with Fernet
- [ ] Audit logging enabled and tested
- [ ] Connection pooling configured with security settings
- [ ] Database backups automated and tested
- [ ] SQL injection protection verified (ORM only)
- [ ] Strong SECRET_KEY generated (64+ characters)
- [ ] DEBUG mode disabled
- [ ] API documentation disabled or restricted
- [ ] HTTPS/TLS enabled
- [ ] Database connections use SSL
- [ ] Firewall rules configured
- [ ] Rate limiting enabled on auth endpoints
- [ ] Account lockout policies configured
- [ ] Monitoring and alerting configured
- [ ] Incident response plan documented

### Regular Maintenance

- [ ] Weekly review of audit logs
- [ ] Monthly backup restoration test
- [ ] Quarterly security audit
- [ ] Update dependencies for security patches
- [ ] Review and rotate credentials annually
- [ ] Test disaster recovery procedures

---

## Support and Contact

For security issues or questions:

1. **Internal Security Team**: security@company.com
2. **Emergency Contact**: +1-XXX-XXX-XXXX
3. **Documentation**: See `/docs` folder for more details

---

## References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [SQLAlchemy Security](https://docs.sqlalchemy.org/en/14/faq/security.html)
- [bcrypt Documentation](https://github.com/pyca/bcrypt/)
- [Fernet Specification](https://github.com/fernet/spec/)
- [PostgreSQL Security](https://www.postgresql.org/docs/current/security.html)

---

**Last Updated**: 2026-02-16  
**Version**: 1.0  
**Maintained By**: DevSecOps Team
