# WSGI service environment

FROM sourcepole/qwc-uwsgi-base:alpine-latest

# Install service packages if needed
RUN apk add --no-cache --update postgresql-dev gcc python3-dev musl-dev git

# maybe set locale here if needed

ADD . /srv/qwc_service
RUN pip3 install --no-cache-dir -r /srv/qwc_service/requirements.txt

ADD pg_service.conf /var/www/.pg_service.conf
ARG DB_USER=qwc_service
ARG DB_PASSWORD=qwc_service
RUN sed -i -e "s/^user=qwc_service/user=$DB_USER/" -e "s/^password=qwc_service/password=$DB_PASSWORD/" /var/www/.pg_service.conf
