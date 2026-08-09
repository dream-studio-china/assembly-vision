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
    fake.onmessage?.({ data: JSON.stringify({ type: "t", sequence: 1, source_id: "s", payload: {} }) });
    fake.onmessage?.({ data: JSON.stringify({ type: "t", sequence: 2, source_id: "s", payload: {} }) });
    expect(seen).toEqual([1, 2]);
  });

  it("drops stale or duplicate envelopes", () => {
    const { ws, fake } = socket();
    const seen: number[] = [];
    ws.subscribe((event) => seen.push(event.sequence));
    fake.onmessage?.({ data: JSON.stringify({ type: "t", sequence: 3, source_id: "s", payload: {} }) });
    fake.onmessage?.({ data: JSON.stringify({ type: "t", sequence: 3, source_id: "s", payload: {} }) });
    fake.onmessage?.({ data: JSON.stringify({ type: "t", sequence: 2, source_id: "s", payload: {} }) });
    expect(seen).toEqual([3]);
  });

  it("signals a gap when events are skipped", () => {
    const { ws, fake } = socket();
    const gaps: number[] = [];
    ws.onGap(() => gaps.push(gaps.length + 1));
    fake.onmessage?.({ data: JSON.stringify({ type: "t", sequence: 1, source_id: "s", payload: {} }) });
    fake.onmessage?.({ data: JSON.stringify({ type: "t", sequence: 4, source_id: "s", payload: {} }) });
    expect(gaps).toHaveLength(1);
  });

  it("does not reset sequence on reconnect (continuity preserved)", () => {
    const { ws, fake } = socket();
    const gaps: number[] = [];
    ws.onGap(() => gaps.push(gaps.length + 1));
    fake.onmessage?.({ data: JSON.stringify({ type: "t", sequence: 2, source_id: "s", payload: {} }) });
    // Reconnect: the server continues at sequence 3, so no gap is signalled.
    fake.onmessage?.({ data: JSON.stringify({ type: "t", sequence: 3, source_id: "s", payload: {} }) });
    expect(gaps).toHaveLength(0);
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
});
