# Redis for the IOS demo pod, serving two ports:
#   6379 (plain) — the bluesky-queueserver RE Manager's own queue store.
#   6380 (TLS)   — the IOS profile's RE.md store. nslsii.configure_base() in the
#                  profile connects with redis_ssl=True, so this port must speak
#                  TLS. The entrypoint self-signs a cert for hostname `redis`.
FROM redis:7-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /usr/local/bin/redis-tls-entrypoint.sh
RUN chmod +x /usr/local/bin/redis-tls-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/redis-tls-entrypoint.sh"]
