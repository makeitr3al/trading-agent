ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.21
FROM ${BUILD_FROM}

ARG BUILD_ARCH
ARG BUILD_VERSION=dev

LABEL io.hass.type="addon" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache python3 py3-pip bash

ENV APP_PATH=/opt/trading-agent
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements/runtime.txt /tmp/requirements.txt
RUN python3 -m venv "${VIRTUAL_ENV}"

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    "${VIRTUAL_ENV}/bin/pip" install -r /tmp/requirements.txt

COPY . ${APP_PATH}
COPY ha_addons/trading_agent/run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR ${APP_PATH}

CMD [ "/run.sh" ]
