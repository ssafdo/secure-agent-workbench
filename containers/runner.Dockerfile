FROM scratch

COPY --chmod=0555 containers/agent-runner /agent-runner
ENV PATH=/
WORKDIR /workspace/work
USER 65532:65532
