# ADR-003: Vue 3 and TypeScript Frontend

## 1. Status

Accepted

## 2. Context

AssemblyVision needs two substantial Web applications: an offline-usable local edge dashboard and a central administration dashboard. They require typed API integration, reusable tables and forms, real-time status, image overlays, review, charts, device/configuration management, and clear error/degraded states.

## 3. Decision

Use Vue 3 and TypeScript with Vite for both frontends. Use Vue Router, Pinia, an OpenAPI-generated client or Axios, a consistently selected component library (Element Plus or Naive UI), ECharts, VueUse, Vitest, ESLint, and Prettier. Share API contracts and proven reusable capabilities while keeping the edge and central applications separate; this decision does not require one package per capability. Initially extract only the generated API client and detection-coordinate/viewer primitives with two concrete consumers. Keep charts, authentication, validation, formatting, stores, and route features local until reuse is demonstrated.

The edge application is served locally and remains usable without central connectivity. A standard browser or kiosk mode is the initial shell; a Tauri wrapper remains a future option.

## 4. Scope

This decision applies to operator/reviewer/administration user interfaces. It does not prescribe camera/inference implementation and does not require a desktop wrapper.

## 5. Consequences

### 5.1 Positive

- One typed component model across edge and central interfaces.
- Effective support for complex administration and visualization.
- Static frontend artifacts are straightforward to serve in containers.
- OpenAPI generation reduces Python/TypeScript contract drift.

### 5.2 Negative and Trade-offs

- Shared packages need governance to avoid coupling the two applications.
- Browser-delivered JavaScript is inspectable and cannot contain secrets.
- Real-time state and offline behavior require explicit reconnection/error design.
- The team must standardize one component library before broad UI implementation.

## 6. Alternatives

- **Server-rendered templates:** rejected because interactive image review, live status, and complex administration exceed a simple template approach.
- **React:** technically viable, but Vue 3 is the selected team/product standard.
- **Tkinter, PyQt, or PySide:** rejected for the main dashboard because they duplicate Web administration capabilities and reduce shared UI code.
- **Tauri immediately:** deferred until a concrete kiosk/device-integration need justifies another packaging layer.

## 7. Open Questions and Validation Required

- Selection between Element Plus and Naive UI.
- Required browsers, kiosk management, localization, and accessibility expectations.
- Whether edge authentication and local network access require additional offline session behavior.

## 8. Links

- [Human-in-the-Loop Operations](../24-human-in-the-loop.md)
- [Security and Source Distribution](../21-security-and-source-distribution.md)
- [ADR-006: REST plus WebSocket](ADR-006-rest-plus-websocket.md)
- [ADR-007: Monorepo](ADR-007-monorepo.md)
