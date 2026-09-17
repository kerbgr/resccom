# ResCCOM 2.1-d — Island Console backend.
#
# A custom image (like ../../../backhaul/Dockerfile), not "mount a script
# into a stock image" (portal/server.py's pattern): this backend imports
# island_init directly -- the same schema/render/signing code
# `island-init check`/`render`/`new` use, so "render --diff from the
# console equals the CLI's output" holds by construction rather than by
# two implementations kept in sync by hand. That needs island_init's own
# pinned dependencies (see island-init/pyproject.toml -- kept identical
# here) and island_init's package source copied in, neither of which the
# stock python image ships.
#
# Build context is the repo root (see ../../compose.yaml's `console`
# service: build.context), not this directory, so this Dockerfile can
# reach island-init/island_init/ -- Docker doesn't allow COPY to escape
# the build context.
#
# 2.1-f: no docker-cli here anymore -- this container never restarts
# services (that, and signing, happen host-side via `island.sh apply`;
# see server.py's own header comment and island_init/apply.py).
FROM python:3.12.11-alpine3.21

# Exact pins from island-init/pyproject.toml.
RUN pip install --no-cache-dir \
      click==8.1.8 \
      jsonschema==4.23.0 \
      "ruamel.yaml==0.18.6" \
      jinja2==3.1.6 \
      cryptography==50.0.1

COPY island-init/island_init /app/island_init
COPY stack/services/config/console/server.py /app/server.py
COPY stack/services/config/console/coverage.py /app/coverage.py
COPY stack/services/config/console/static /app/static
COPY stack/services/config/console/vendor /app/vendor

WORKDIR /app
ENV PYTHONPATH=/app
ENTRYPOINT ["python3", "/app/server.py"]
