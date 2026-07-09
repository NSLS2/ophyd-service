#!/bin/sh
# Generate a self-signed cert (once) into the shared /certs volume, then run
# redis with both a plain port (queue store) and a TLS port (profile RE.md).
# The queueserver container trusts /certs/redis.crt via SSL_CERT_FILE.
set -e

CERT_DIR=/certs
mkdir -p "$CERT_DIR"

if [ ! -f "$CERT_DIR/redis.crt" ]; then
    echo "redis-tls-entrypoint: generating self-signed cert for CN=redis"
    openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
        -keyout "$CERT_DIR/redis.key" \
        -out    "$CERT_DIR/redis.crt" \
        -subj   "/CN=redis" \
        -addext "subjectAltName=DNS:redis,DNS:localhost,IP:127.0.0.1"
    chmod 644 "$CERT_DIR/redis.crt" "$CERT_DIR/redis.key"
fi

exec redis-server \
    --port 6379 \
    --tls-port 6380 \
    --tls-cert-file    "$CERT_DIR/redis.crt" \
    --tls-key-file     "$CERT_DIR/redis.key" \
    --tls-ca-cert-file "$CERT_DIR/redis.crt" \
    --tls-auth-clients no \
    --save '' \
    --appendonly no
