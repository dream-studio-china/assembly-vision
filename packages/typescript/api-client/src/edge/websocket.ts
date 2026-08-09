// WebSocket event service (docs/design/16-edge-dashboard.md section 16.10).
//
// Carries low-latency transient notifications only; REST remains the source
// of truth. On reconnect or a sequence gap the UI marks data stale and
// refetches REST snapshots. This MVP ships the connection/backoff contract and
// a no-op local implementation; the backend event feed is wired later.

export type WSStatus = "disconnected" | "connecting" | "connected";

/**
 * One version-1 runtime event envelope (design 15.6, PR-023 F04).
 * Field names mirror the server payload exactly; the event payload is `data`.
 */
export type WSEventEnvelope = {
  event_id: string;
  type: string;
  schema_version: number;
  occurred_at: string;
  source_id: string;
  sequence: number;
  correlation_id: string | null;
  data: unknown;
};

function isEventEnvelope(value: unknown): value is WSEventEnvelope {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.event_id === "string" &&
    typeof v.type === "string" &&
    typeof v.schema_version === "number" &&
    typeof v.occurred_at === "string" &&
    typeof v.source_id === "string" &&
    typeof v.sequence === "number" &&
    (typeof v.correlation_id === "string" || v.correlation_id === null) &&
    "data" in v
  );
}

/**
 * Resolves the WebSocket subprotocols for one (re)connect attempt. Providers
 * are re-invoked on every connect so single-use credentials such as the
 * runtime ticket can be refreshed (PR-023 F01).
 */
export type WebSocketProtocolProvider = () => Promise<string[]>;

export interface WebSocketService {
  readonly status: WSStatus;
  /** Connect (or reconnect) to the event feed, optionally with subprotocols. */
  connect(url: string, protocols?: string[] | WebSocketProtocolProvider): void;
  /** Close the feed; no reconnect is scheduled. */
  disconnect(): void;
  /** Subscribe to typed envelopes. Returns an unsubscribe function. */
  subscribe(listener: (event: WSEventEnvelope) => void): () => void;
  /**
   * Subscribe to sequence-gap notifications. A gap means events were lost;
   * the caller must refetch REST state. Sequence is not reset on reconnect,
   * so reconnects that preserve continuity do not signal a gap.
   */
  onGap(listener: () => void): () => void;
}

function backoffDelay(attempt: number, baseMs = 1000, maxMs = 30000): number {
  const cap = Math.min(baseMs * 2 ** attempt, maxMs);
  return cap / 2 + Math.random() * (cap / 2);
}

/**
 * Browser WebSocket service with exponential backoff and jitter.
 * Envelopes whose sequence is not strictly increasing (per source_id) are
 * dropped and signal a gap; the caller must refetch REST state.
 */
export class ReconnectingWebSocket implements WebSocketService {
  #socket: WebSocket | null = null;
  #url = "";
  #protocols: string[] | WebSocketProtocolProvider | null = null;
  #attempt = 0;
  #timer: ReturnType<typeof setTimeout> | null = null;
  #listeners: Array<(event: WSEventEnvelope) => void> = [];
  #gapListeners: Array<() => void> = [];
  #lastSequence = new Map<string, number>();
  #manualClose = false;

  status: WSStatus = "disconnected";

  connect(url: string, protocols?: string[] | WebSocketProtocolProvider): void {
    this.#url = url;
    this.#protocols = protocols ?? null;
    this.#manualClose = false;
    void this.#open();
  }

  disconnect(): void {
    this.#manualClose = true;
    if (this.#timer !== null) {
      clearTimeout(this.#timer);
      this.#timer = null;
    }
    this.#socket?.close();
    this.#socket = null;
    this.status = "disconnected";
  }

  subscribe(listener: (event: WSEventEnvelope) => void): () => void {
    this.#listeners.push(listener);
    return () => {
      this.#listeners = this.#listeners.filter((l) => l !== listener);
    };
  }

  onGap(listener: () => void): () => void {
    this.#gapListeners.push(listener);
    return () => {
      this.#gapListeners = this.#gapListeners.filter((l) => l !== listener);
    };
  }

  async #open(): Promise<void> {
    this.status = "connecting";
    let protocols: string[] = [];
    if (typeof this.#protocols === "function") {
      try {
        protocols = await this.#protocols();
      } catch {
        // A failed credential exchange must not crash the caller; retry with
        // backoff so a transient ticket outage recovers (PR-023 F01).
        this.#scheduleReconnect();
        return;
      }
    } else if (this.#protocols !== null) {
      protocols = this.#protocols;
    }
    let socket: WebSocket;
    try {
      socket =
        protocols.length > 0
          ? new WebSocket(this.#url, protocols)
          : new WebSocket(this.#url);
    } catch {
      this.#scheduleReconnect();
      return;
    }
    this.#socket = socket;
    socket.onopen = () => {
      this.#attempt = 0;
      this.status = "connected";
    };
    socket.onmessage = (message: MessageEvent<string>) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(message.data);
      } catch {
        return;
      }
      // Malformed envelopes are dropped before sequence handling so they can
      // never corrupt the per-source baseline (PR-023 F04).
      if (!isEventEnvelope(parsed)) return;
      const envelope = parsed;
      const previous = this.#lastSequence.get(envelope.source_id) ?? -1;
      if (previous >= 0 && envelope.sequence > previous + 1) {
        // Missing events after an established baseline: signal the gap so
        // callers refetch REST state.
        for (const listener of this.#gapListeners) listener();
      }
      if (envelope.sequence <= previous) return; // stale or duplicate
      this.#lastSequence.set(envelope.source_id, envelope.sequence);
      for (const listener of this.#listeners) listener(envelope);
    };
    socket.onclose = () => {
      this.#socket = null;
      this.status = "disconnected";
      if (!this.#manualClose) this.#scheduleReconnect();
    };
    socket.onerror = () => {
      socket.close();
    };
  }

  #scheduleReconnect(): void {
    if (this.#manualClose || this.#timer !== null) return;
    const delay = backoffDelay(this.#attempt);
    this.#attempt += 1;
    this.#timer = setTimeout(() => {
      this.#timer = null;
      void this.#open();
    }, delay);
  }
}
