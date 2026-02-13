# Security Guide for Employee Cabinet

This document provides security guidelines for setting up, deploying, and maintaining the Employee Cabinet application.

## Table of Contents
- [Quick Start](#quick-start)
- [Environment Setup](#environment-setup)
- [Development Environment](#development-environment)
- [Production Deployment](#production-deployment)
- [Credentials Management](#credentials-management)
- [Security Checklist](#security-checklist)
- [Incident Response](#incident-response)

---

## Quick Start

### First Time Setup

1. **Copy the environment template:**
   ```bash
   cp .env.example .env
   ```

2. **Generate secure secrets:**
   ```bash
   python generate_secrets.py --type all
   ```

3. **Update your .env file with the generated secrets**

4. **Never commit .env files to git!**

---

## Environment Setup

### Required Environment Variables

The application requires the following critical environment variables:

#### 🔐 Security Credentials

| Variable | Description | Minimum Length | Example |
|----------|-------------|----------------|---------|
| `SECRET_KEY` | Application secret key for JWT signing | 32 chars (64 recommended) | Generate with `generate_secrets.py` |
| `SWAGGER_USERNAME` | Username for Swagger docs access | - | `admin` |
| `SWAGGER_PASSWORD` | Password for Swagger docs access | 16 chars | Generate with `generate_secrets.py` |
| `POSTGRES_PASSWORD` | Database password | 16 chars | Generate with `generate_secrets.py` |
| `SMTP_PASSWORD` | Email service password | - | From your email provider |

#### 📊 Database Configuration

```bash
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=employee_cabinet
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<strong-password>

# Optional: Or provide full URL
# DATABASE_URL=postgresql://user:password@host:port/dbname
```

#### 🔴 Redis Configuration

```bash
redis_host=localhost
redis_port=6379

# Optional: Or provide full URL
# REDIS_URL=redis://localhost:6379/0
```

---

## Development Environment

### Setting Up Development

1. **Create .env file from template:**
   ```bash
   cp .env.example .env
   ```

2. **Generate development secrets:**
   ```bash
   python generate_secrets.py --type all
   ```

3. **Configure development settings in .env:**
   ```bash
   DEBUG=true
   ENVIRONMENT=development
   ENABLE_DOCS=true
   DOCS_REQUIRE_AUTH=true
   ```

4. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

5. **Run database migrations:**
   ```bash
   alembic upgrade head
   ```

6. **Start the application:**
   ```bash
   uvicorn app.main:app --reload
   ```

### Development Best Practices

- ✅ **DO** use different credentials for dev/staging/production
- ✅ **DO** keep your .env file locally and never commit it
- ✅ **DO** use `ENABLE_DOCS=true` in development
- ✅ **DO** test with `DOCS_REQUIRE_AUTH=true` enabled
- ❌ **DON'T** use production credentials in development
- ❌ **DON'T** share your .env file with others
- ❌ **DON'T** commit secrets to git

---

## Production Deployment

### Pre-Deployment Security Checklist

Before deploying to production, ensure:

- [ ] `DEBUG=false` in production environment
- [ ] `ENVIRONMENT=production` is set
- [ ] `SECRET_KEY` is cryptographically random (min 64 chars)
- [ ] `ENABLE_DOCS=false` or restricted with `DOCS_ALLOWED_IPS`
- [ ] `DOCS_REQUIRE_AUTH=true` if docs are enabled
- [ ] All passwords are strong and unique (min 32 chars)
- [ ] CORS origins are restricted to known domains
- [ ] Database uses SSL/TLS connections
- [ ] SMTP credentials use app-specific passwords
- [ ] `.env` files are NOT in git repository
- [ ] Secrets are stored in secure vault (not .env files)

### Production Deployment Methods

#### Option 1: Environment Variables (Recommended)

```bash
# Set environment variables directly in your deployment platform
export SECRET_KEY="your-64-char-secret-key"
export SWAGGER_PASSWORD="your-strong-password"
export POSTGRES_PASSWORD="your-db-password"
# ... other variables
```

#### Option 2: Docker Secrets

```yaml
# docker-compose.yml
services:
  app:
    secrets:
      - secret_key
      - postgres_password
    environment:
      SECRET_KEY_FILE: /run/secrets/secret_key
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password

secrets:
  secret_key:
    external: true
  postgres_password:
    external: true
```

#### Option 3: Kubernetes Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: employee-cabinet-secrets
type: Opaque
data:
  secret-key: <base64-encoded-secret>
  postgres-password: <base64-encoded-password>
```

#### Option 4: Cloud Provider Secret Management

- **AWS**: AWS Secrets Manager or Parameter Store
- **Azure**: Azure Key Vault
- **GCP**: Google Cloud Secret Manager
- **DigitalOcean**: App Platform Environment Variables

### Production Configuration Example

```bash
# Production .env settings (use secret management instead!)
DEBUG=false
ENVIRONMENT=production
SECRET_KEY=<64-char-cryptographically-random-key>

# Disable or restrict documentation
ENABLE_DOCS=false
# OR if you need docs in production:
ENABLE_DOCS=true
DOCS_REQUIRE_AUTH=true
DOCS_ALLOWED_IPS=["10.0.0.0/8"]  # Restrict to internal network

# Strong, unique passwords
SWAGGER_PASSWORD=<32-char-strong-password>
POSTGRES_PASSWORD=<32-char-strong-password>

# Restrict CORS to known domains
CORS_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
```

---

## Credentials Management

### Generating Secrets

Use the provided `generate_secrets.py` utility:

```bash
# Generate SECRET_KEY
python generate_secrets.py --type secret_key

# Generate a strong password
python generate_secrets.py --type password

# Generate all secrets at once
python generate_secrets.py --type all

# Custom length (for extra security)
python generate_secrets.py --type secret_key --length 128
python generate_secrets.py --type password --length 48
```

### Secret Rotation

Rotate secrets periodically:

1. **SECRET_KEY rotation:**
   - Generate new key: `python generate_secrets.py --type secret_key`
   - Deploy new key to production
   - All users will need to re-authenticate
   - Old sessions will be invalidated

2. **Password rotation:**
   - Generate new password: `python generate_secrets.py --type password`
   - Update in secret management system
   - Deploy updated configuration
   - Test access with new credentials

### What NOT to Do

❌ **NEVER** hardcode secrets in source code
❌ **NEVER** commit .env files to git
❌ **NEVER** share secrets via email/chat
❌ **NEVER** use the same secret across environments
❌ **NEVER** use weak or guessable passwords
❌ **NEVER** log secrets or passwords
❌ **NEVER** include secrets in error messages

---

## Security Checklist

### Development Checklist
- [ ] Created .env from .env.example
- [ ] Generated strong SECRET_KEY (min 32 chars)
- [ ] Set unique passwords for all services
- [ ] Verified .env is in .gitignore
- [ ] Tested application starts successfully
- [ ] Verified Swagger authentication works

### Staging Checklist
- [ ] All development checklist items
- [ ] DEBUG=false
- [ ] ENVIRONMENT=staging
- [ ] Different credentials from development
- [ ] DOCS_REQUIRE_AUTH=true
- [ ] Tested with production-like configuration

### Production Checklist
- [ ] All staging checklist items
- [ ] ENVIRONMENT=production
- [ ] SECRET_KEY is 64+ characters
- [ ] ENABLE_DOCS=false (or restricted with DOCS_ALLOWED_IPS)
- [ ] Unique, strong passwords (32+ chars)
- [ ] CORS restricted to known domains
- [ ] Secrets stored in vault (not .env files)
- [ ] Database connections use SSL/TLS
- [ ] Regular security audits scheduled
- [ ] Incident response plan documented
- [ ] Backup and recovery tested

---

## Incident Response

### If Credentials Are Leaked

If credentials are accidentally committed to git or leaked:

#### Immediate Actions (Within 1 hour)

1. **Rotate all compromised credentials:**
   ```bash
   python generate_secrets.py --type all
   ```

2. **Update production secrets immediately:**
   - Update SECRET_KEY (will invalidate all sessions)
   - Update SWAGGER_PASSWORD
   - Update POSTGRES_PASSWORD
   - Update SMTP_PASSWORD

3. **Revoke git history (if committed):**
   ```bash
   # Remove from git history (use with caution!)
   git filter-branch --force --index-filter \
     "git rm --cached --ignore-unmatch .env" \
     --prune-empty --tag-name-filter cat -- --all
   
   # Force push to remote
   git push origin --force --all
   git push origin --force --tags
   ```

4. **Notify team members:**
   - Inform all developers
   - Update deployment documentation
   - Schedule credential rotation training

#### Follow-up Actions (Within 24 hours)

- [ ] Review access logs for suspicious activity
- [ ] Audit all systems that used compromised credentials
- [ ] Update incident response documentation
- [ ] Schedule security training for team
- [ ] Review and improve credential management processes

#### Prevention Measures

- Enable pre-commit hooks to detect secrets
- Use git-secrets or similar tools
- Regular security audits
- Mandatory code reviews
- Developer security training

### Monitoring

Regularly check for:
- Failed authentication attempts
- Unusual access patterns
- Suspicious API usage
- Database connection anomalies
- Unauthorized Swagger access

---

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [Python Cryptography](https://cryptography.io/)
- [Twelve-Factor App](https://12factor.net/)

---

## Support

For security concerns or questions:
- Email: security@example.com
- Internal Security Team: #security-team
- Security Hotline: +1-XXX-XXX-XXXX

**Remember: Security is everyone's responsibility!** 🔐
