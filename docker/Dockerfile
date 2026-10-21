# OpenQQ QQ Sync Bridge —— Linux/Docker 版
# 纯标准库实现，不需要任何第三方依赖。
FROM python:3.11-slim

LABEL org.opencontainers.image.title="OpenQQ QQ Sync Bridge"
LABEL org.opencontainers.image.description="OpenQQ 与旧 QQ 数据迁移同步桥（Docker 版）"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OPENQQ_BRIDGE_ROOT=/config \
    OPENQQ_BRIDGE_DATA_DIR=/data \
    OPENQQ_BRIDGE_PORT=38999

WORKDIR /app

COPY bridge.py /app/bridge.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh \
 && mkdir -p /config /data \
 && useradd --create-home --uid 10001 bridge \
 && chown -R bridge:bridge /app /config /data

USER bridge

# 38999 = 同步桥端口（JS 插件通过它通信）
EXPOSE 38999

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import json,os,urllib.request; p=os.environ.get('OPENQQ_BRIDGE_PORT','38999'); r=json.load(urllib.request.urlopen('http://127.0.0.1:'+p+'/health',timeout=4)); raise SystemExit(0 if r.get('ok') else 1)"

ENTRYPOINT ["/app/entrypoint.sh"]
