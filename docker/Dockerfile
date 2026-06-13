FROM python:3.12-slim-bookworm

WORKDIR /app

# Latest releases available at https://ghproxy.cn/https://github.com/aptible/supercronic/releases
ARG TARGETARCH
ENV SUPERCRONIC_VERSION=v0.2.39

RUN apt-get update && \
      apt-get install -y --no-install-recommends ca-certificates && \
      apt-get clean && \
      rm -rf /var/lib/apt/lists/*

# 用宿主机预下载的 supercronic 二进制 (绕开国内 github.com)
COPY docker/supercronic-linux-amd64 /usr/local/bin/supercronic
RUN chmod +x /usr/local/bin/supercronic && supercronic -version

# 从官方镜像拷贝 uv 二进制
#COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 先安装依赖（利用 Docker 层缓存）
#COPY pyproject.toml uv.lock ./
#RUN --mount=type=cache,target=/root/.cache/uv \
#    uv sync --locked --no-install-project --no-dev

# 用 pip 直接装依赖 (国内 ghcr.io 不稳定,绕开 uv)
COPY requirements.txt ./
RUN pip install --no-cache-dir \
      -i https://mirrors.tencent.com/pypi/simple/ \
      -r requirements.txt

# 再复制项目代码并安装项目本身
COPY docker/manage.py .
COPY trendradar/ ./trendradar/
COPY scripts/ ./scripts/
#RUN --mount=type=cache,target=/root/.cache/uv \
#    uv sync --locked --no-dev

#ENV PATH="/app/.venv/bin:$PATH"

# 复制 entrypoint.sh 并强制转换为 LF 格式
COPY docker/entrypoint.sh /entrypoint.sh.tmp
RUN sed -i 's/\r$//' /entrypoint.sh.tmp && \
    mv /entrypoint.sh.tmp /entrypoint.sh && \
    chmod +x /entrypoint.sh && \
    chmod +x manage.py && \
    mkdir -p /app/config /app/output

ENV PYTHONUNBUFFERED=1 \
    CONFIG_PATH=/app/config/config.yaml \
    FREQUENCY_WORDS_PATH=/app/config/frequency_words.txt

ENTRYPOINT ["/entrypoint.sh"]
