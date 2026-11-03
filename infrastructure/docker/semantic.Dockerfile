ARG BASE_IMAGE=csh-foundry-api:phase10-amd64
FROM ${BASE_IMAGE} AS install
USER root
RUN python scripts/install_semantic_engine.py
RUN cp .external/open-ontologies /usr/local/bin/open-ontologies
USER 10001:10001
ENV OPEN_ONTOLOGIES_BIN=/usr/local/bin/open-ontologies
CMD ["python", "-m", "ontology_platform.jobs.supervisor", "--kind", "semantic", "--ontology", "manufacturing", "--deadline", "60"]
