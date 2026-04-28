# Security Configuration for taia-browser-harness

## Overview

This document describes the security measures implemented in the taia-browser-harness MCP server and how to configure additional security settings.

## Security Features Implemented

### 1. Non-Root User Execution
The container now runs as a non-root user (`appuser`) to limit the attack surface.

### 2. Chromium Security Hardening
Chromium is launched with multiple security flags:
- `--no-sandbox` (required for Docker)
- `--disable-dev-shm-usage`
- `--disable-extensions` - Prevents loading of extensions
- `--disable-component-extensions` - Disables built-in extensions
- `--disable-background-networking` - Blocks background network requests
- `--disable-sync` - Disables synchronization features
- `--disable-infobars` - Removes info bars

### 3. SSRF Protection
The `is_url_safe()` function blocks:
- Loopback addresses (127.0.0.0/8)
- RFC-1918 private networks (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- Link-local addresses (169.254.0.0/16)
- Cloud metadata endpoints (100.64.0.0/10)
- Internal hostnames (mongodb, ollama, meilisearch, etc.)

### 4. Rate Limiting
Token bucket and burst limiters prevent abuse:
- `BROWSER_RATE_LIMIT_MAX` (default: 500) - Maximum requests per connection
- `BROWSER_RATE_LIMIT_REFILL` (default: 50.0) - Token refill rate per second
- `BROWSER_BURST_LIMIT_MAX` (default: 100) - Max requests per window
- `BROWSER_BURST_LIMIT_WINDOW` (default: 60) - Time window in seconds

### 5. Input Sanitization
JavaScript evaluation scripts are sanitized to prevent:
- Script length limits (50KB max)
- Dangerous pattern detection (eval, fetch, XMLHttpRequest, etc.)
- Null byte removal

### 6. CORS Configuration
CORS is configurable via `BROWSER_CORS_ALLOWED_ORIGINS` environment variable.

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BROWSER_HEADLESS` | `true` | Run browser without UI |
| `BROWSER_MAX_SESSIONS` | `100` | Max simultaneous sessions |
| `BROWSER_SESSION_TIMEOUT_MINUTES` | `30` | Session inactivity timeout |
| `BROWSER_RATE_LIMIT_MAX` | `500` | Token bucket capacity |
| `BROWSER_RATE_LIMIT_REFILL` | `50.0` | Token refill rate/sec |
| `BROWSER_BURST_LIMIT_MAX` | `100` | Burst limit per window |
| `BROWSER_BURST_LIMIT_WINDOW` | `60` | Burst window (seconds) |
| `BROWSER_CORS_ALLOWED_ORIGINS` | `*` | Allowed CORS origins (comma-separated) |
| `BROWSER_PROXY` | `` | HTTP proxy server URL |

### Docker Compose Security Settings

The browser-harness service includes:
- Resource limits (8 CPU, 16GB memory for high-performance)
- Read-only filesystem (`read_only: true`)
- No-new-privileges security option
- Capability restrictions
- No host port exposure (internal network only)
- tmpfs mounts for temporary files

## Recommendations for Production

1. **Enable Authentication**: Implement API keys or JWT authentication before the SSE endpoint
2. **Network Isolation**: Keep the browser-harness on an internal network, never expose port 8005 to the host
3. **Rate Limit Tuning**: Adjust rate limits based on your workload:
   ```yaml
   environment:
     BROWSER_RATE_LIMIT_MAX: "50"      # Lower for stricter limits
     BROWSER_RATE_LIMIT_REFILL: "5.0"  # Lower for stricter limits
   ```
4. **CORS Restrictions**: In production, specify exact origins:
   ```yaml
   BROWSER_CORS_ALLOWED_ORIGINS: "https://yourdomain.com,https://app.yourdomain.com"
   ```
5. **Monitoring**: Enable security logging for audit purposes
6. **Regular Updates**: Keep Playwright and Chromium updated for security patches

## High-Performance Configuration

For 30+ concurrent users with powerful hardware (2x RTX A6000, 128GB RAM):

```yaml
environment:
  BROWSER_MAX_SESSIONS: "100"
  BROWSER_RATE_LIMIT_MAX: "500"
  BROWSER_RATE_LIMIT_REFILL: "50.0"
  BROWSER_BURST_LIMIT_MAX: "100"
deploy:
  resources:
    limits:
      cpus: "8.0"
      memory: "16G"
    reservations:
      cpus: "4.0"
      memory: "8G"
tmpfs:
  - /tmp:mode=1777,size=512M
  - /run:mode=1777,size=64M
```

This configuration supports:
- 100 concurrent browser sessions
- 10 sessions per user
- 500 requests/second per connection
- 8 CPU cores for parallel execution
- 16GB RAM for browser instances

## Known Limitations

1. **No Built-in Authentication**: The server does not implement authentication - implement at the reverse proxy level if needed
2. **CORS Wildcard**: Default CORS allows all origins - configure for production
3. **Rate Limit Storage**: Rate limit data is stored in memory - not shared across replicas

## Audit Logging

Security events are logged with the `security` logger:
- Connection establishment with remote IP
- Rate limit violations
- Session creation and destruction