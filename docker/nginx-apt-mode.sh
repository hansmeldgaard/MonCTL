#!/bin/sh
# MonCTL apt-cache mode entrypoint
# Writes /etc/nginx/conf.d/upstream.conf based on APT_CACHE_MODE env var.
# Modes:
#   direct  — upstream archive.ubuntu.com directly
#   proxy   — upstream via CORP_PROXY_URL (HTTP forward proxy)
#   offline — serve from local mirror at /srv/apt-mirror (no upstream)

set -e

MODE="${APT_CACHE_MODE:-direct}"
UPSTREAM_CONF="/etc/nginx/conf.d/upstream.conf"
SERVER_CONF="/etc/nginx/conf.d/default.conf"

# nginx:alpine uses /etc/nginx/templates/default.conf.template → envsubst → default.conf
# We need to also seed the upstream.conf include file.

case "$MODE" in
    direct)
        cat > "$UPSTREAM_CONF" <<EOF
upstream apt_upstream {
    server archive.ubuntu.com:80;
    keepalive 16;
}
upstream apt_security_upstream {
    server security.ubuntu.com:80;
    keepalive 16;
}
EOF
        echo "[apt-cache] mode=direct (upstream: archive.ubuntu.com)"
        ;;

    proxy)
        if [ -z "${CORP_PROXY_URL:-}" ]; then
            echo "[apt-cache] ERROR: APT_CACHE_MODE=proxy but CORP_PROXY_URL not set" >&2
            exit 1
        fi
        # Parse CORP_PROXY_URL: http://host:port  →  host:port
        PROXY_HOST_PORT=$(echo "$CORP_PROXY_URL" | sed -E 's#^https?://##; s#/.*##')
        cat > "$UPSTREAM_CONF" <<EOF
upstream apt_upstream {
    server ${PROXY_HOST_PORT};
    keepalive 16;
}
upstream apt_security_upstream {
    server ${PROXY_HOST_PORT};
    keepalive 16;
}
EOF
        # In proxy mode, the corp proxy forwards to archive.ubuntu.com via Host header (set in server config).
        echo "[apt-cache] mode=proxy (via ${PROXY_HOST_PORT})"
        ;;

    offline)
        # Empty upstream — we rewrite the location to serve from disk
        cat > "$UPSTREAM_CONF" <<'EOF'
# Offline mode — no upstream, local mirror only
upstream apt_upstream     { server 127.0.0.1:1; }
upstream apt_security_upstream { server 127.0.0.1:1; }
EOF
        # Override locations to serve from local mirror
        cat > /etc/nginx/conf.d/offline-override.conf <<'EOF'
# Offline mode — served by MonCTL apt-cache
EOF
        # Patch the server config to use file serving (done via sed on the template post-envsubst)
        echo "[apt-cache] mode=offline (local mirror at /srv/apt-mirror)"
        ;;

    *)
        echo "[apt-cache] ERROR: unknown APT_CACHE_MODE='$MODE' (use direct|proxy|offline)" >&2
        exit 1
        ;;
esac

# For offline mode, swap the server config to serve from filesystem
if [ "$MODE" = "offline" ]; then
    cat > "$SERVER_CONF" <<'EOF'
server {
    listen 18080 default_server;
    server_name _;

    access_log /var/log/nginx/apt-access.log combined;

    location /ubuntu/ {
        alias /srv/apt-mirror/ubuntu/;
        autoindex on;
        add_header X-Cache-Status "OFFLINE" always;
    }

    location /security/ {
        alias /srv/apt-mirror/security/;
        autoindex on;
        add_header X-Cache-Status "OFFLINE" always;
    }

    location = /health {
        access_log off;
        return 200 "ok\n";
        add_header Content-Type text/plain;
    }

    location = /cache-status {
        stub_status;
        allow 127.0.0.1;
        deny all;
    }
}
EOF
fi
