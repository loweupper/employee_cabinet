# 🔒 Security Hardening Implementation Guide

## Overview

This document describes the comprehensive security enhancements implemented in the Employee Cabinet application to protect against common web vulnerabilities.

## Security Enhancements Implemented

### 1. File Upload Security

**Location:** `app/modules/documents/routes.py`, `app/modules/documents/service.py`

**Protections:**
- ✅ **File Size Validation** - Maximum 10MB per file (configurable via `MAX_FILE_SIZE`)
- ✅ **File Type Whitelist** - Only allows safe file extensions
- ✅ **Filename Sanitization** - Prevents directory traversal attacks
- ✅ **Extension Validation** - Cross-checks file extensions

**Allowed File Types:**
```python
ALLOWED_DOCUMENT_EXTENSIONS = {
    'pdf',      # Adobe PDF
    'doc',      # Microsoft Word (legacy)
    'docx',     # Microsoft Word
    'xls',      # Microsoft Excel (legacy)
    'xlsx',     # Microsoft Excel
    'jpg',      # JPEG images
    'jpeg',     # JPEG images
    'png',      # PNG images
    'gif',      # GIF images
    'txt',      # Plain text
    'csv',      # CSV data
}
```

**Implementation Details:**
```python
# Check file size
if file.size > settings.MAX_FILE_SIZE:
    raise HTTPException(status_code=413, detail="File too large")

# Check file extension
if not validate_file_extension(file.filename, ALLOWED_DOCUMENT_EXTENSIONS):
    raise HTTPException(status_code=400, detail="File type not allowed")

# Sanitize filename
safe_filename = sanitize_filename(file.filename)
```

### 2. CSRF Protection

**Location:** `app/main.py`

**Implementation:**
```python
from starlette_csrf import CSRFMiddleware

app.add_middleware(
    CSRFMiddleware,
    secret=settings.SECRET_KEY,
    cookie_name="csrftoken",
    cookie_secure=settings.ENVIRONMENT == "production",
    cookie_httponly=False,  # Needs to be False for JavaScript access
    cookie_samesite="lax",
    header_name="X-CSRFToken",
    safe_methods={"GET", "HEAD", "OPTIONS", "TRACE"},
)
```

**Features:**
- ✅ Automatic CSRF token generation
- ✅ Token validation on state-changing requests (POST, PUT, DELETE)
- ✅ Secure cookie settings
- ✅ SameSite protection

**For Template Forms:**
CSRF tokens are automatically handled by the middleware. The token is available in cookies as `csrftoken`.

### 3. Rate Limiting

**Location:** `app/main.py`, `app/modules/auth/routes.py`, `app/modules/documents/routes.py`, `app/modules/profile/routes.py`

**Implementation:**
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

**Rate Limits Applied:**

| Endpoint | Rate Limit | Purpose |
|----------|------------|---------|
| `/api/v1/auth/register` | 3/minute | Prevent spam registrations |
| `/api/v1/auth/login` | 5/minute | Prevent brute force attacks |
| `/objects/*/documents/upload` | 10/hour | Prevent DoS via file uploads |
| `/profile/update` | 30/minute | Prevent profile update abuse |

**Usage Example:**
```python
@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, ...):
    ...
```

### 4. CORS Hardening

**Location:** `app/core/config.py`

**Before:**
```python
CORS_METHODS: list[str] = ["*"]  # ⚠️ Allows all methods
CORS_HEADERS: list[str] = ["*"]  # ⚠️ Allows all headers
```

**After:**
```python
CORS_METHODS: list[str] = ["GET", "POST", "PUT", "DELETE"]  # ✅ Explicit methods only
CORS_HEADERS: list[str] = ["Content-Type", "Authorization"]  # ✅ Explicit headers only
```

**Benefits:**
- ✅ Prevents unauthorized HTTP methods
- ✅ Restricts custom headers
- ✅ Reduces attack surface

### 5. Input Validation Utilities

**Location:** `app/core/validators.py`

**Functions:**

#### `sanitize_filename(filename: str) -> str`
Removes dangerous characters from filenames to prevent directory traversal attacks.

**Examples:**
```python
>>> sanitize_filename("../../etc/passwd")
'etcpasswd'
>>> sanitize_filename("file<script>.txt")
'file_script_.txt'
```

#### `sanitize_html(text: str) -> str`
Removes HTML/script tags to prevent XSS attacks.

**Examples:**
```python
>>> sanitize_html("<script>alert('xss')</script>Hello")
'&lt;script&gt;alert('xss')&lt;/script&gt;Hello'
>>> sanitize_html("Normal text")
'Normal text'
```

#### `validate_file_extension(filename: str, allowed_extensions: set) -> bool`
Checks if file extension is in the allowed list.

**Examples:**
```python
>>> validate_file_extension("document.pdf", ALLOWED_DOCUMENT_EXTENSIONS)
True
>>> validate_file_extension("script.exe", ALLOWED_DOCUMENT_EXTENSIONS)
False
```

## Configuration

### Environment Variables

Add to your `.env` file:

```bash
# Security Settings
SECRET_KEY=your-secret-key-here  # Required for CSRF
ENVIRONMENT=production  # production, staging, or development
MAX_FILE_SIZE=10485760  # 10MB in bytes

# CORS Settings
CORS_ORIGINS=["https://yourdomain.com", "https://www.yourdomain.com"]
CORS_METHODS=["GET", "POST", "PUT", "DELETE"]
CORS_HEADERS=["Content-Type", "Authorization"]

# Rate Limiting (already configured)
RATE_LIMIT_ENABLED=true
```

## Testing

### Test File Upload Validation

**Test large file rejection:**
```bash
# Create a large file (>10MB)
dd if=/dev/zero of=/tmp/large_file.bin bs=1M count=11

# Attempt upload (should fail with 413)
curl -X POST http://localhost:8001/objects/1/documents/upload \
  -F "files=@/tmp/large_file.bin" \
  -F "category=general" \
  -b "access_token=YOUR_TOKEN"
# Expected: Error message about file size
```

**Test invalid file type:**
```bash
# Create an executable file
echo "#!/bin/bash" > /tmp/malicious.sh

# Attempt upload (should fail with 400)
curl -X POST http://localhost:8001/objects/1/documents/upload \
  -F "files=@/tmp/malicious.sh" \
  -F "category=general" \
  -b "access_token=YOUR_TOKEN"
# Expected: Error message about file type
```

### Test Rate Limiting

**Test login rate limit:**
```bash
# Try logging in 6 times rapidly
for i in {1..6}; do
  curl -X POST http://localhost:8001/api/v1/auth/login \
    -d "email=test@example.com&password=wrong" \
    -H "Content-Type: application/x-www-form-urlencoded"
  echo ""
done
# Expected: First 5 requests process normally, 6th returns 429 Too Many Requests
```

### Test CSRF Protection

**Without CSRF token:**
```bash
curl -X POST http://localhost:8001/profile/update \
  -d "first_name=Test" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -b "access_token=YOUR_TOKEN"
# Expected: 403 Forbidden (CSRF token missing)
```

**With CSRF token:**
```bash
# First get the CSRF token
TOKEN=$(curl -c cookies.txt http://localhost:8001/profile | grep csrftoken)

# Then make request with token
curl -X POST http://localhost:8001/profile/update \
  -d "first_name=Test" \
  -H "X-CSRFToken: TOKEN_VALUE" \
  -b cookies.txt
# Expected: Success
```

## Security Best Practices

### 1. Keep Dependencies Updated
```bash
pip list --outdated
pip install --upgrade starlette-csrf bleach slowapi
```

### 2. Regular Security Audits
```bash
# Check for known vulnerabilities
pip-audit

# Run security linters
bandit -r app/
```

### 3. Monitor Rate Limits
- Review rate limit logs regularly
- Adjust limits based on legitimate usage patterns
- Set up alerts for repeated rate limit violations

### 4. HTTPS in Production
Always use HTTPS in production:
```python
# In production .env
ENVIRONMENT=production
# This automatically sets:
# - cookie_secure=True for CSRF
# - secure=True for session cookies
```

### 5. Regular Penetration Testing
- Test file upload with malicious files
- Attempt CSRF attacks on forms
- Try brute force attacks on auth endpoints
- Test for directory traversal in filenames

## Migration Guide

### For Existing Deployments

1. **Update Dependencies:**
```bash
pip install -r requirements.txt
```

2. **Update Environment Variables:**
Add the new security settings to your `.env` file.

3. **Test in Staging:**
Test all form submissions and file uploads in staging environment first.

4. **Deploy to Production:**
```bash
# Pull latest code
git pull origin main

# Install dependencies
pip install -r requirements.txt

# Restart application
systemctl restart employee-cabinet
```

5. **Monitor Logs:**
Watch for any CSRF or rate limiting errors in the first 24 hours.

## Troubleshooting

### CSRF Token Errors

**Problem:** Forms returning 403 Forbidden

**Solution:** Ensure cookies are enabled and the `csrftoken` cookie is being sent with requests.

### Rate Limit False Positives

**Problem:** Legitimate users getting rate limited

**Solution:** Adjust rate limits in the route decorators:
```python
@limiter.limit("10/minute")  # Increase from 5/minute
async def login(...):
    ...
```

### File Upload Rejections

**Problem:** Valid files being rejected

**Solution:** Check if the file extension is in `ALLOWED_DOCUMENT_EXTENSIONS`. Add new extensions if needed:
```python
# In app/core/validators.py
ALLOWED_DOCUMENT_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx',
    'jpg', 'jpeg', 'png', 'gif', 'txt', 'csv',
    'zip',  # Add new extension
}
```

## Security Incident Response

If you detect a security breach:

1. **Immediate Actions:**
   - Review access logs
   - Check for unusual file uploads
   - Review rate limit violations

2. **Investigation:**
   - Identify attack vector
   - Assess data exposure
   - Document timeline

3. **Remediation:**
   - Patch vulnerabilities
   - Update security policies
   - Notify affected users if needed

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [OWASP CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [slowapi Documentation](https://slowapi.readthedocs.io/)
- [Starlette CSRF Documentation](https://github.com/simonw/starlette-csrf)

## Compliance

These security enhancements help meet requirements for:
- ✅ OWASP Top 10 protection
- ✅ GDPR data security requirements
- ✅ PCI DSS (if handling payment data)
- ✅ SOC 2 security controls

## Change Log

### Version 1.0.0 (Current)
- ✅ Implemented file upload security
- ✅ Added CSRF protection
- ✅ Configured rate limiting
- ✅ Hardened CORS settings
- ✅ Created input validation utilities

---

**Last Updated:** 2026-02-13
**Maintained By:** Security Team
**Review Cycle:** Quarterly
