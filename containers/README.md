# Container runner

`runner.Dockerfile` is the network-free image used by the Phase 8 executor smoke test.
It contains one statically linked `agent-runner` binary and uses `scratch`, so the build
does not download a base image. Build the binary from `agent-runner.s` with GNU `as` and
`ld`, then inspect the immutable local image ID (`sha256:<64 hex>`). A registry image may
instead use `name@sha256:<64 hex>`. Do not put API keys in this image.
