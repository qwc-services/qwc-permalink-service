# WSGI service environment

FROM sourcepole/qwc-uwsgi-base:alpine-v2021.12.16

# Install service packages if needed
RUN apk add --no-cache --update postgresql-dev gcc python3-dev musl-dev git

# maybe set locale here if needed

ADD . /srv/qwc_service
RUN pip3 install --no-cache-dir -r /srv/qwc_service/requirements.txt
