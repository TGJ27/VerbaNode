# Plugin security and reliability model

VerbaNode external plugins are trusted local Python code. They execute inside the VerbaNode Core process and can access resources available to that process. The plugin system is not an untrusted-code sandbox.

## Reliability protections

v0.6.3 adds:

- Strict manifest, path, permission, semantic-version, and tool-schema validation.
- Duplicate and reserved ID protection.
- Bounded concurrent plugin executions.
- Per-execution timeout and cancellation propagation.
- Consecutive-failure tracking and automatic `unhealthy` state.
- Safe reload that keeps the previous working version when replacement code is invalid.
- Shutdown-hook timeout.
- Isolated failed, invalid, and incompatible package reporting.

## Operator responsibility

Review source code before installation. Do not install unknown plugins on a robot or system that has access to movement, cameras, microphones, credentials, files, networks, or shell commands. Permission declarations are informational and do not prevent undeclared access.


## v0.8.2 capability providers

First-party robot/device/service integrations should expose namespaced operations through `CapabilityProvider` and be invoked by plugins through `PluginContext.gateway.invoke(...)`. The gateway validates declared permissions and the provider service adds bounded concurrency, timeout, TTL/expiry, and cancellation handling. This is an application architecture boundary; it does not make arbitrary external Python plugins untrusted or sandboxed.
