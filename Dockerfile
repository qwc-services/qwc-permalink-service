FROM sourcepole/qwc-uwsgi-base:alpine-v2025.01.24

WORKDIR /srv/qwc_service
ADD pyproject.toml uv.lock ./

# git: Required for pip with git repos
# postgresql-dev g++ python3-dev: Required for psycopg2
RUN \
    apk add --no-cache --update --virtual runtime-deps postgresql-libs && \
    apk add --no-cache --update --virtual build-deps git postgresql-dev g++ python3-dev && \
    uv sync --frozen && \
    uv cache clean && \
    apk del build-deps

ADD src /srv/qwc_service/

ENV SERVICE_MOUNTPOINT=/api/v1/permalink
# Support very long URLs (14k)
# https://uwsgi-docs.readthedocs.io/en/latest/Options.html#buffer-size
ENV REQ_HEADER_BUFFER_SIZE=14336
