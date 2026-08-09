import { describe, expect, it, vi } from "vitest";

import { ReconnectingWebSocket } from "../src/edge/websocket";

/**
 * A minimal fake WebSocket whose onmessage/onopen handlers can be triggered
 * directly, so sequence-gap behavior is deterministic.
 */
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public url: string, public protocols: string[] = []) {
    FakeWebSocket.instances.push(this);
  }

  close(): void {
    this.onclose?.();
  }
}

/** A real version-1 server envelope (design 15.6, PR-023 F04). */
function envelope(sequence: number, overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({
    event_id: `0199-${sequence}`,
    type: "inspection.completed",
    schema_version: 1,
    occurred_at: "2026-08-10T00:00:00Z",
    source_id: "dev-1",
    sequence,
    correlation_id: null,
    data: { inspection_id: "i-1", instance_id: "line-1" },
    ...overrides,
  });
}

function socket(): { ws: ReconnectingWebSocket; fake: FakeWebSocket } {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
  const ws = new ReconnectingWebSocket();
  ws.connect("ws://edge.test/events");
  return { ws, fake: FakeWebSocket.instances[0]! };
}

describe("ReconnectingWebSocket sequence handling (AUDIT-001 4.5)", () => {
  it("delivers envelopes in strict sequence order", () => {
    const { ws, fake } = socket();
    const seen: number[] = [];
    ws.subscribe((event) => seen.push(event.sequence));
    fake.onmessage?.({ data: envelope(1) });
    fake.onmessage?.({ data: envelope(2) });
    expect(seen).toEqual([1, 2]);
  });

  it("exposes the full v1 envelope fields including data", () => {
    const { ws, fake } = socket();
    let received: Record<string, unknown> | null = null;
    ws.subscribe((event) => {
      received = { ...event, data: event.data };
    });
    fake.onmessage?.({ data: envelope(7) });
    expect(received).toMatchObject({
      event_id: "0199-7",
      type: "inspection.completed",
      schema_version: 1,
      occurred_at: "2026-08-10T00:00:00Z",
      source_id: "dev-1",
      sequence: 7,
      correlation_id: null,
      data: { inspection_id: "i-1", instance_id: "line-1" },
    });
  });

  it("drops stale or duplicate envelopes", () => {
    const { ws, fake } = socket();
    const seen: number[] = [];
    ws.subscribe((event) => seen.push(event.sequence));
    fake.onmessage?.({ data: envelope(3) });
    fake.onmessage?.({ data: envelope(3) });
    fake.onmessage?.({ data: envelope(2) });
    expect(seen).toEqual([3]);
  });

  it("signals a gap when events are skipped", () => {
    const { ws, fake } = socket();
    const gaps: number[] = [];
    ws.onGap(() => gaps.push(gaps.length + 1));
    fake.onmessage?.({ data: envelope(1) });
    fake.onmessage?.({ data: envelope(4) });
    expect(gaps).toHaveLength(1);
  });

  it("does not reset sequence on reconnect (continuity preserved)", () => {
    const { ws, fake } = socket();
    const gaps: number[] = [];
    ws.onGap(() => gaps.push(gaps.length + 1));
    fake.onmessage?.({ data: envelope(2) });
    // Reconnect: the server continues at sequence 3, so no gap is signalled.
    fake.onmessage?.({ data: envelope(3) });
    expect(gaps).toHaveLength(0);
  });

  it("drops malformed envelopes without corrupting the sequence baseline", () => {
    const { ws, fake } = socket();
    const seen: number[] = [];
    ws.subscribe((event) => seen.push(event.sequence));
    fake.onmessage?.({ data: JSON.stringify({ type: "t", sequence: 99, source_id: "s", payload: {} }) });
    fake.onmessage?.({ data: "not json" });
    fake.onmessage?.({ data: envelope(1) });
    // The legacy-shaped and invalid messages are ignored; the first valid
    // envelope establishes the baseline at 1 (PR-023 F04).
    expect(seen).toEqual([1]);
  });

  it("passes static subprotocols to the socket", () => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
    const ws = new ReconnectingWebSocket();
    ws.connect("ws://edge.test/events", ["av-runtime-v1"]);
    const fake = FakeWebSocket.instances[0]!;
    expect(fake.protocols).toEqual(["av-runtime-v1"]);
  });

  it("resolves protocol providers before each connect (single-use tickets)", async () => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
    const ws = new ReconnectingWebSocket();
    const tickets: string[] = [];
    ws.connect("ws://edge.test/events", async () => {
      tickets.push("issued");
      return ["ticket-1"];
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    const fake = FakeWebSocket.instances[0]!;
    expect(fake.protocols).toEqual(["ticket-1"]);
    expect(tickets).toEqual(["issued"]);
  });

  it("does not open a socket after disconnect during a ticket exchange", async () => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
    let resolveTicket: ((value: string[]) => void) | undefined;
    const ticket = new Promise<string[]>((resolve) => {
      resolveTicket = resolve;
    });
    const ws = new ReconnectingWebSocket();
    ws.connect("ws://edge.test/events", () => ticket);
    ws.disconnect();
    resolveTicket?.(["ticket-after-disconnect"]);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("ignores an old socket closing after a newer connection starts", () => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
    const ws = new ReconnectingWebSocket();
    ws.connect("ws://edge.test/first");
    const first = FakeWebSocket.instances[0]!;
    ws.connect("ws://edge.test/second");
    const second = FakeWebSocket.instances[1]!;
    second.onopen?.();
    first.onclose?.();
    expect(ws.status).toBe("connected");
  });
});
