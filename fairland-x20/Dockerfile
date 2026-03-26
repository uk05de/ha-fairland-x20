ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache python3 py3-pip

WORKDIR /srv

RUN python3 -m venv ./venv
RUN . ./venv/bin/activate && pip install --no-cache-dir pymodbus paho-mqtt PyYAML

COPY run.sh /srv/run.sh
RUN chmod +x /srv/run.sh

COPY src/ /srv/src/

ENTRYPOINT ["/srv/run.sh"]
