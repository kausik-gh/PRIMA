import { useCallback, useEffect, useRef, useState } from "react";
import type { WsEvent } from "../types";
import { wsUrl } from "./api";

type Options = {
  onDead?: (code: number) => void;
};

export function useTopicSocket(
  path: string | null,
  onEvent: (event: WsEvent) => void,
  onStatus?: (connected: boolean) => void,
  options?: Options,
): { send: (payload: unknown) => void; reconnecting: boolean } {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const status = useRef(onStatus);
  status.current = onStatus;
  const dead = useRef(options?.onDead);
  dead.current = options?.onDead;
  const socketRef = useRef<WebSocket | null>(null);
  const [reconnecting, setReconnecting] = useState(false);

  useEffect(() => {
    if (!path) {
      return;
    }
    let closed = false;
    let retry: number | undefined;
    let delay = 500;

    const connect = () => {
      const socket = new WebSocket(wsUrl(path));
      socketRef.current = socket;
      socket.onopen = () => {
        delay = 500;
        setReconnecting(false);
        status.current?.(true);
      };
      socket.onmessage = (message) => {
        try {
          handler.current(JSON.parse(message.data) as WsEvent);
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = (event) => {
        status.current?.(false);
        socketRef.current = null;
        if (event.code === 4404) {
          dead.current?.(event.code);
          return;
        }
        if (!closed) {
          setReconnecting(true);
          retry = window.setTimeout(connect, delay);
          delay = Math.min(delay * 2, 8000);
        }
      };
    };

    connect();
    return () => {
      closed = true;
      if (retry) {
        window.clearTimeout(retry);
      }
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [path]);

  const send = useCallback((payload: unknown) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
    }
  }, []);

  return { send, reconnecting };
}
