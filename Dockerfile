FROM sourcepole/qwc-uwsgi-base:alpine-v2022.01.26

ADD . /srv/qwc_service

# git: Required for pip with git repos
# postgresql-dev g++ python3-dev: Required for psycopg2-binary
RUN \
    apk add --no-cache --update --virtual runtime-deps postgresql-libs && \
    apk add --no-cache --update --virtual build-deps git postgresql-dev g++ python3-dev && \
    pip3 install --no-cache-dir -r /srv/qwc_service/requirements.txt && \
    apk del build-deps

ENV SERVICE_MOUNTPOINT=/api/v1/permalink
# Support very long URLs (14k)
# https://uwsgi-docs.readthedocs.io/en/latest/Options.html#buffer-size
ENV REQ_HEADER_BUFFER_SIZE=14336
