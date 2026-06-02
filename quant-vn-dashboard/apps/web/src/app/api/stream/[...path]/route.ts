import { NextRequest } from "next/server";
import { env } from "@/lib/env";
import { createClient } from "@/lib/supabase/server";

/**
 * Server-Sent Events BFF proxy.
 *
 * Browsers' built-in EventSource cannot set an Authorization header, so the
 * browser connects to this same-origin endpoint and we forward the request
 * to FastAPI with the user's Supabase access token attached. The upstream
 * response body is piped straight back as ``text/event-stream``.
 *
 * Path mapping:
 *   GET /api/stream/quotes?…              → ${API}/stream/quotes?…
 *   GET /api/stream/watchlist/<id>        → ${API}/stream/watchlist/<id>
 *   GET /api/stream/market-overview       → ${API}/stream/market-overview
 *
 * Cloudflare Pages requires dynamic route handlers to run on the Edge runtime.
 * The response body stays streamed through to the browser as SSE.
 */
export const runtime = "edge";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session) {
    return new Response("Unauthorized", { status: 401 });
  }

  const search = new URL(req.url).search;
  const upstream = `${env.apiBaseUrl}/stream/${path.join("/")}${search}`;

  const upstreamResp = await fetch(upstream, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      Accept: "text/event-stream",
    },
    // Propagate disconnects upstream when the browser closes the EventSource.
    signal: req.signal,
  });

  if (!upstreamResp.ok && upstreamResp.status !== 200) {
    return new Response(upstreamResp.statusText, { status: upstreamResp.status });
  }

  return new Response(upstreamResp.body, {
    status: upstreamResp.status,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
