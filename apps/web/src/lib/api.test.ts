import { describe, expect, it, vi } from "vitest";

import {
  ApiError,
  getActiveDiagnosticSession,
  getMarketResearchHistory,
  getMarketResearchOverview,
  messageForError,
  redactMarketResearchSource,
  recoverPreDispatchMarketResearch,
  reconcileMarketResearchRecovery,
  synthesizeMarketResearch,
} from "./api";

describe("diagnostic API helpers", () => {
  it("treats a missing active session as an empty state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              code: "active_session_not_found",
              message: "No active session.",
            },
          }),
          { status: 404, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(
      getActiveDiagnosticSession("algorithm", "0.2.0"),
    ).resolves.toBeNull();
    vi.unstubAllGlobals();
  });

  it("keeps server error messages available to the interface", () => {
    expect(messageForError(new ApiError(409, "conflict", "已有活动会话"))).toBe(
      "已有活动会话",
    );
  });

  it("requires the caller to send the explicit market synthesis confirmation", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "run-1",
          status: "review_pending",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await synthesizeMarketResearch("run-1", {
      confirm_external_ai: true,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/market-research/runs/run-1/synthesis",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ confirm_external_ai: true }),
      }),
    );
    vi.unstubAllGlobals();
  });

  it("requests bounded market research history", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ runs: [], events: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getMarketResearchHistory(10);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/market-research/history?limit=10",
      expect.objectContaining({
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
    vi.unstubAllGlobals();
  });

  it("filters market research by the locked goal context", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          catalog: {},
          budget: {},
          available_contexts: [],
          latest_run: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getMarketResearchOverview("goal-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/market-research/overview?goal_selection_id=goal-1",
      expect.any(Object),
    );
    vi.unstubAllGlobals();
  });

  it("requires explicit recovery reconciliation without another model call", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "run-1", status: "failed" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await reconcileMarketResearchRecovery("run-1", {
      confirm_end: true,
      note: "close only",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/market-research/runs/run-1/reconcile-recovery",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ confirm_end: true, note: "close only" }),
      }),
    );
    vi.unstubAllGlobals();
  });

  it("separates pre-dispatch recovery confirmation from model synthesis", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "run-1", status: "synthesis_pending" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await recoverPreDispatchMarketResearch("run-1", {
      confirm_recovery: true,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/market-research/runs/run-1/recover-pre-dispatch",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ confirm_recovery: true }),
      }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it("sends an explicit source redaction confirmation without exposing content", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "run-1", status: "blocked" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await redactMarketResearchSource("run-1", "source/1", {
      confirm_redaction: true,
      reason: "user confirmed",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/market-research/runs/run-1/sources/source%2F1/redact",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          confirm_redaction: true,
          reason: "user confirmed",
        }),
      }),
    );
    vi.unstubAllGlobals();
  });
});
