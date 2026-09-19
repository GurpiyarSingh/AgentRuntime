/* Agent Runtime — chat client.
 *
 * Talks to POST /v1/chat/stream, which emits Server-Sent Events for every
 * decision the agent loop makes. EventSource can't do POST, so we read the
 * response body as a stream and parse the SSE framing ourselves. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const els = {
    transcript: $("transcript"),
    emptyState: $("empty-state"),
    suggestions: $("suggestions"),
    composer: $("composer"),
    input: $("input"),
    send: $("send"),
    stop: $("stop"),
    newChat: $("new-chat"),
    model: $("model"),
    agent: $("agent"),
    agentList: $("agent-list"),
    agentCount: $("agent-count"),
    clearAgent: $("clear-agent"),
    emailNotice: $("email-notice"),
    emailNoticeText: $("email-notice-text"),
    sessionUsage: $("session-usage"),
    sessionUsageText: $("session-usage-text"),
    status: $("status"),
    statusText: $("status-text"),
    brandSub: $("brand-sub"),
    trace: $("trace"),
    traceList: $("trace-list"),
    toggleTrace: $("toggle-trace"),
    clearTrace: $("clear-trace"),
  };

  /** @type {string|null} */
  let sessionId = null;
  /** @type {AbortController|null} */
  let controller = null;
  /** Running token/cost total for the whole conversation. */
  let sessionTotals = { input: 0, output: 0, total: 0, cost: 0, priced: false };

  const MODEL_KEY = "agent-runtime.model";
  const AGENT_KEY = "agent-runtime.agent";
  /** Agents as the server described them, for the sidebar. */
  let agentCards = new Map();
  /** False when /v1/models couldn't be reached: the picker stays disabled. */
  let modelsAvailable = true;

  // ---------------------------------------------------------------- helpers

  const setStatus = (state, text) => {
    els.status.dataset.state = state;
    els.statusText.textContent = text;
  };

  const atBottom = () => {
    const el = els.transcript;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };

  const scrollDown = (force = false) => {
    if (force || atBottom()) {
      els.transcript.scrollTop = els.transcript.scrollHeight;
    }
  };

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const pretty = (value) => {
    if (value === null || value === undefined) return "";
    if (typeof value === "string") return value;
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  };

  const setBusy = (busy) => {
    els.transcript.setAttribute("aria-busy", busy ? "true" : "false");
    els.send.disabled = busy;
    els.stop.hidden = !busy;
    els.input.disabled = busy;
    // Switching models mid-run would misreport what produced the answer.
    els.model.disabled = busy || !modelsAvailable;
    els.agent.disabled = busy;
    if (!busy) els.input.focus();
  };

  const formatTokens = (n) => Number(n || 0).toLocaleString();

  /** Small bills need more decimals than big ones to say anything at all. */
  const formatCost = (cost) => {
    if (cost === null || cost === undefined) return "cost n/a";
    if (cost === 0) return "$0";
    if (cost < 0.01) return "$" + cost.toFixed(6);
    if (cost < 1) return "$" + cost.toFixed(4);
    return "$" + cost.toFixed(2);
  };

  function addToSessionTotals(usage) {
    if (!usage) return;
    sessionTotals.input += usage.input_tokens || 0;
    sessionTotals.output += usage.output_tokens || 0;
    sessionTotals.total += usage.total_tokens || 0;
    if (typeof usage.cost_usd === "number") {
      sessionTotals.cost += usage.cost_usd;
      sessionTotals.priced = true;
    }
    els.sessionUsage.hidden = false;
    els.sessionUsageText.textContent =
      formatTokens(sessionTotals.total) +
      " tok · " +
      formatCost(sessionTotals.priced ? sessionTotals.cost : null);
    els.sessionUsage.title =
      "This conversation so far: " +
      formatTokens(sessionTotals.input) +
      " input + " +
      formatTokens(sessionTotals.output) +
      " output tokens";
  }

  function resetSessionTotals() {
    sessionTotals = { input: 0, output: 0, total: 0, cost: 0, priced: false };
    els.sessionUsage.hidden = true;
    els.sessionUsageText.textContent = "0 tok · $0";
  }

  // ------------------------------------------------------------ run render

  /** Builds the DOM for one agent run and returns handlers for its events. */
  function createRunView() {
    const wrap = el("div", "run");
    els.transcript.appendChild(wrap);

    /** @type {Map<string, HTMLElement>} tool call id -> card */
    const cards = new Map();
    /** @type {HTMLElement|null} */
    let answerNode = null;
    /** @type {HTMLElement|null} */
    let usageNode = null;
    /** @type {HTMLElement|null} */
    let routeNode = null;
    let lastStep = 0;

    const ensureAnswer = () => {
      if (!answerNode) {
        answerNode = el("div", "answer streaming");
        wrap.appendChild(answerNode);
      }
      return answerNode;
    };

    return {
      step(step) {
        // A new step means any prior streamed text is settled.
        if (answerNode) answerNode.classList.remove("streaming");
        if (step > 1 && step !== lastStep) {
          wrap.appendChild(el("span", "step-label", `Step ${step}`));
        }
        lastStep = step;
        answerNode = null;
        scrollDown();
      },

      token(text) {
        ensureAnswer().textContent += text;
        scrollDown();
      },

      toolStart(data) {
        if (answerNode) answerNode.classList.remove("streaming");
        answerNode = null;

        const card = el("details", "tool-card");
        card.dataset.state = "running";
        card.open = false;

        const head = el("summary", "tool-head");
        head.appendChild(el("span", "tool-icon", "⚙"));
        head.appendChild(el("span", "tool-name", data.tool_name));
        const meta = el("span", "tool-meta");
        const spin = el("span", "spin");
        meta.appendChild(spin);
        head.appendChild(meta);
        card.appendChild(head);

        const body = el("div", "tool-body");
        const argsBlock = el("div");
        argsBlock.appendChild(el("div", "kv-label", "Arguments"));
        argsBlock.appendChild(el("pre", "code", pretty(data.arguments) || "{}"));
        body.appendChild(argsBlock);
        card.appendChild(body);

        cards.set(data.call_id, card);
        wrap.appendChild(card);
        scrollDown();
      },

      toolResult(data) {
        const card = cards.get(data.call_id);
        if (!card) return;

        card.dataset.state = data.is_error ? "error" : "done";
        const icon = card.querySelector(".tool-icon");
        if (icon) icon.textContent = data.is_error ? "!" : "✓";

        const meta = card.querySelector(".tool-meta");
        if (meta) {
          meta.textContent = "";
          if (typeof data.duration_s === "number") {
            meta.appendChild(el("span", null, `${(data.duration_s * 1000).toFixed(0)} ms`));
          }
          meta.appendChild(el("span", null, data.is_error ? "failed" : "ok"));
        }

        const body = card.querySelector(".tool-body");
        if (body) {
          const block = el("div");
          block.appendChild(el("div", "kv-label", data.is_error ? "Error" : "Result"));
          const pre = el("pre", "code", pretty(data.content));
          if (data.is_error) pre.classList.add("is-error");
          block.appendChild(pre);
          body.appendChild(block);
        }
        if (data.is_error) card.open = true;
        scrollDown();
      },

      final(text) {
        const node = ensureAnswer();
        node.classList.remove("streaming");
        // With token streaming off (or a tool-only turn), fill in the answer.
        if (!node.textContent.trim() && text) node.textContent = text;
        if (!node.textContent.trim()) node.remove();
        // An answer created after the usage event would otherwise land
        // below it; the cost footer always closes out the message.
        if (usageNode) wrap.appendChild(usageNode);
        scrollDown();
      },

      /** Which agent the orchestrator handed this turn to. */
      routed(data) {
        routeNode = el("div", "route");
        routeNode.appendChild(el("span", "route-agent", data.label || data.agent));
        routeNode.appendChild(el("span", "route-why", data.reason || ""));
        routeNode.title = `Routed by: ${data.routed_by}. Available: ${(data.available || []).join(", ")}`;
        wrap.appendChild(routeNode);
        scrollDown();
      },

      /** Live cost of this message; re-rendered after every model call. */
      usage(data) {
        const run = data.run_usage || {};
        if (!usageNode) {
          usageNode = el("div", "usage");
          wrap.appendChild(usageNode);
        }
        usageNode.textContent = "";
        usageNode.appendChild(el("span", "usage-model", data.model || ""));
        usageNode.appendChild(el("span", "usage-item", formatTokens(run.input_tokens) + " in"));
        usageNode.appendChild(el("span", "usage-item", formatTokens(run.output_tokens) + " out"));
        usageNode.appendChild(el("span", "usage-total", formatTokens(run.total_tokens) + " tok"));
        const cost = el("span", "usage-cost", formatCost(run.cost_usd));
        if (run.cost_usd === null || run.cost_usd === undefined) cost.classList.add("is-unpriced");
        usageNode.appendChild(cost);
        usageNode.title =
          "This message: " +
          formatTokens(run.input_tokens) +
          " input + " +
          formatTokens(run.output_tokens) +
          " output tokens on " +
          (data.model || "the selected model");
        // The footer belongs at the end of the run, below whatever came after it.
        wrap.appendChild(usageNode);
        scrollDown();
      },

      failed(reason) {
        if (answerNode) answerNode.classList.remove("streaming");
        const banner = el("div", "banner");
        banner.appendChild(el("strong", null, "Run failed"));
        banner.appendChild(el("span", null, reason || "The agent run did not complete."));
        wrap.appendChild(banner);
        // Even a failed run shows what it spent before it gave up.
        if (usageNode) wrap.appendChild(usageNode);
        scrollDown(true);
      },

      settle() {
        if (answerNode) answerNode.classList.remove("streaming");
        for (const card of cards.values()) {
          if (card.dataset.state === "running") {
            card.dataset.state = "error";
            const meta = card.querySelector(".tool-meta");
            if (meta) meta.textContent = "interrupted";
          }
        }
      },
    };
  }

  // ----------------------------------------------------------------- trace

  function addTrace(type, data) {
    const item = el("li", "trace-item");
    item.dataset.kind = type;
    item.appendChild(el("span", "trace-type", type));

    let detail = "";
    if (type === "step_started") detail = ` step ${data.step}`;
    else if (type === "tool_call_requested") detail = ` ${data.tool_name} ${pretty(data.arguments)}`;
    else if (type === "tool_call_result") {
      detail = ` ${data.tool_name} → ${String(data.content ?? "").slice(0, 90)}`;
    } else if (type === "final_answer") detail = ` ${String(data.content ?? "").slice(0, 90)}`;
    else if (type === "run_failed") detail = ` ${data.reason ?? ""}`;
    else if (type === "run_started") detail = ` max_steps ${data.max_steps}`;
    else if (type === "agent_selected") detail = ` ${data.agent} (${data.routed_by})`;
    else if (type === "agent_completed") detail = ` ${data.agent} → ${data.status}`;
    else if (type === "usage_updated") {
      const run = data.run_usage || {};
      detail = ` ${data.model} · ${formatTokens(run.total_tokens)} tok · ${formatCost(run.cost_usd)}`;
    }

    if (detail) item.appendChild(el("span", "trace-detail", detail));
    els.traceList.appendChild(item);
    els.traceList.scrollTop = els.traceList.scrollHeight;
  }

  // ------------------------------------------------------------ SSE client

  /** Splits a raw SSE frame into {event, data}. */
  function parseFrame(frame) {
    let event = "message";
    const dataLines = [];
    for (const line of frame.split(/\r?\n/)) {
      if (!line || line.startsWith(":")) continue; // keep-alive comment
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (!dataLines.length) return null;
    try {
      return { event, data: JSON.parse(dataLines.join("\n")) };
    } catch {
      return null;
    }
  }

  async function streamRun(message, view) {
    controller = new AbortController();

    const response = await fetch("/v1/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({
        message,
        session_id: sessionId,
        model: els.model.value || null,
        agent: els.agent.value || null,
      }),
      signal: controller.signal,
    });

    if (!response.ok || !response.body) {
      throw new Error(`Server responded ${response.status} ${response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let sawTerminal = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let match;
      while ((match = /\r?\n\r?\n/.exec(buffer)) !== null) {
        const frame = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);

        const parsed = parseFrame(frame);
        if (!parsed) continue;

        const { event, data } = parsed;
        if (data.session_id) sessionId = data.session_id;
        addTrace(event, data);

        switch (event) {
          case "agent_selected":
            setStatus("running", `${data.label || data.agent}`);
            markRunning(data.agent);
            view.routed(data);
            break;
          case "run_started":
            setStatus("running", `Running · up to ${data.max_steps} steps`);
            break;
          case "step_started":
            setStatus("running", `Step ${data.step}`);
            view.step(data.step);
            break;
          case "model_token":
            view.token(data.text || "");
            break;
          case "tool_call_requested":
            setStatus("running", `Calling ${data.tool_name}`);
            view.toolStart(data);
            break;
          case "tool_call_result":
            view.toolResult(data);
            break;
          case "agent_completed":
            sawTerminal = sawTerminal || data.status === "completed";
            clearRunning();
            break;
          case "usage_updated":
            view.usage(data);
            // Session totals add up per model call, not per run, so a run
            // that fails midway still counts what it already spent.
            addToSessionTotals(data.step_usage);
            break;
          case "final_answer":
            sawTerminal = true;
            view.final(data.content || "");
            setStatus("ok", "Done");
            break;
          case "run_failed":
            sawTerminal = true;
            view.failed(data.reason);
            setStatus("error", "Failed");
            break;
        }
      }
    }

    if (!sawTerminal) {
      view.failed("The stream ended before the agent produced an answer.");
      setStatus("error", "Interrupted");
    }
  }

  // -------------------------------------------------------------- actions

  async function submit(message) {
    const text = message.trim();
    if (!text || els.send.disabled) return;

    els.emptyState?.remove();
    els.emptyState = null;

    const userMsg = el("div", "msg msg-user");
    userMsg.appendChild(el("div", "bubble", text));
    els.transcript.appendChild(userMsg);

    els.input.value = "";
    autosize();
    scrollDown(true);
    setBusy(true);
    setStatus("running", "Thinking");

    const view = createRunView();
    try {
      await streamRun(text, view);
    } catch (error) {
      if (error.name === "AbortError") {
        view.settle();
        view.failed("Stopped.");
        setStatus("idle", "Stopped");
      } else {
        view.settle();
        view.failed(String(error.message || error));
        setStatus("error", "Error");
      }
    } finally {
      // A stopped or failed stream may never send agent_completed.
      clearRunning();
      controller = null;
      setBusy(false);
    }
  }

  function autosize() {
    els.input.style.height = "auto";
    els.input.style.height = `${Math.min(els.input.scrollHeight, 180)}px`;
  }

  async function loadHealth() {
    try {
      const res = await fetch("/health");
      if (!res.ok) throw new Error(String(res.status));
      const info = await res.json();
      const agents = (info.agents || []).join(", ");
      // The active model lives in the picker now, so it isn't repeated here.
      els.brandSub.textContent = `${info.environment} · agents: ${agents || "none"}`;
      showEmailStatus(info.email || {});
      setStatus("ok", "Ready");
    } catch {
      els.brandSub.textContent = "server unreachable";
      setStatus("error", "Offline");
    }
  }

  /** Says plainly whether mail will really be sent — never let this be a surprise. */
  function showEmailStatus(email) {
    if (!email.dry_run) {
      els.emailNotice.hidden = true;
      return;
    }
    const sender = email.sender ? ` No mail leaves ${email.sender}.` : "";
    els.emailNoticeText.textContent =
      "The email agent will compose and validate messages, but nothing is actually sent." +
      sender +
      " Set EMAIL_DRY_RUN=false with SMTP configured to send for real.";
    els.emailNotice.hidden = false;
  }

  /** Draws one agent in the sidebar: what it does, its state, its tools. */
  function renderAgentCard(agent) {
    const card = el("button", "agent-card");
    card.type = "button";
    card.dataset.agent = agent.name;
    card.dataset.ready = agent.ready === false ? "false" : "true";
    // A caveat (like a dry run) is not a failure, so it gets its own colour.
    card.dataset.caveat = agent.ready !== false && agent.status ? "true" : "false";
    card.setAttribute("aria-pressed", "false");

    const top = el("div", "agent-top");
    top.appendChild(el("span", "agent-dot"));
    top.appendChild(el("span", "agent-name", agent.label || agent.name));
    top.appendChild(el("span", "agent-pinned", ""));
    card.appendChild(top);

    card.appendChild(el("p", "agent-desc", agent.description || ""));
    if (agent.status) card.appendChild(el("span", "agent-status", agent.status));

    const tools = el("div", "agent-tools");
    for (const tool of agent.tools || []) tools.appendChild(el("span", "agent-tool", tool));
    if (!(agent.tools || []).length) tools.appendChild(el("span", "agent-tool", "no tools"));
    card.appendChild(tools);

    card.title = agent.status
      ? `${agent.description}

${agent.status}`
      : agent.description || "";
    card.addEventListener("click", () => {
      // Clicking the pinned agent again returns to auto routing.
      setAgent(els.agent.value === agent.name ? "" : agent.name);
    });
    return card;
  }

  /** Single source of truth for the agent choice: picker, sidebar, storage. */
  function setAgent(name) {
    els.agent.value = name;
    store(AGENT_KEY, name);
    for (const [agentName, card] of agentCards) {
      const pinned = agentName === name;
      card.setAttribute("aria-pressed", pinned ? "true" : "false");
      const badge = card.querySelector(".agent-pinned");
      if (badge) badge.textContent = pinned ? "pinned" : "";
    }
    els.clearAgent.hidden = !name;
  }

  /** Marks which agent is currently working, from the routing event. */
  function markRunning(name) {
    for (const [agentName, card] of agentCards) {
      card.dataset.running = agentName === name ? "true" : "false";
    }
  }

  function clearRunning() {
    for (const card of agentCards.values()) card.dataset.running = "false";
  }

  /** Fills the agent picker; 'Auto' lets the orchestrator decide. */
  async function loadAgents() {
    try {
      const res = await fetch("/v1/agents");
      if (!res.ok) throw new Error(String(res.status));
      const info = await res.json();
      const agents = info.agents || [];
      els.agent.textContent = "";

      const auto = el("option", null, "Auto");
      auto.value = "";
      auto.title = "Let the orchestrator route this request.";
      els.agent.appendChild(auto);

      for (const agent of agents) {
        const option = el("option", null, agent.label || agent.name);
        option.value = agent.name;
        option.title = `${agent.description || ""} (tools: ${(agent.tools || []).join(", ")})`;
        els.agent.appendChild(option);
      }
      els.agentList.textContent = "";
      agentCards = new Map();
      for (const agent of agents) {
        const card = renderAgentCard(agent);
        agentCards.set(agent.name, card);
        const item = el("li");
        item.appendChild(card);
        els.agentList.appendChild(item);
      }
      els.agentCount.textContent = String(agents.length);

      const saved = readStored(AGENT_KEY);
      setAgent(agents.some((a) => a.name === saved) ? saved : "");
    } catch {
      els.agent.textContent = "";
      const option = el("option", null, "Auto");
      option.value = "";
      els.agent.appendChild(option);
      els.agentList.textContent = "";
      els.agentList.appendChild(el("li", "sidebar-note", "Agent list unavailable."));
    }
  }

  /** Fills the model picker from the server, so it can only offer real choices. */
  async function loadModels() {
    try {
      const res = await fetch("/v1/models");
      if (!res.ok) throw new Error(String(res.status));
      const info = await res.json();
      const models = info.models || [];
      els.model.textContent = "";
      for (const model of models) {
        const option = el("option", null, model.label || model.id);
        option.value = model.id;
        option.title = `${model.description || ""} ($${model.input_usd_per_1m}/1M in, $${model.output_usd_per_1m}/1M out)`;
        els.model.appendChild(option);
      }
      const saved = readStored(MODEL_KEY);
      els.model.value = models.some((m) => m.id === saved) ? saved : info.default || "";
    } catch {
      els.model.textContent = "";
      const option = el("option", null, "models unavailable");
      option.value = "";
      els.model.appendChild(option);
      modelsAvailable = false;
      els.model.disabled = true;
    }
  }

  function readStored(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null; // private mode / blocked storage: fall back to the default
    }
  }

  function store(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* not worth failing a chat over */
    }
  }

  // --------------------------------------------------------------- events

  els.composer.addEventListener("submit", (event) => {
    event.preventDefault();
    submit(els.input.value);
  });

  els.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit(els.input.value);
    }
  });

  els.input.addEventListener("input", autosize);

  els.suggestions?.addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (chip) submit(chip.dataset.prompt || chip.textContent);
  });

  els.stop.addEventListener("click", () => controller?.abort());

  els.model.addEventListener("change", () => store(MODEL_KEY, els.model.value));

  els.agent.addEventListener("change", () => setAgent(els.agent.value));

  els.clearAgent.addEventListener("click", () => setAgent(""));

  els.newChat.addEventListener("click", () => {
    controller?.abort();
    sessionId = null;
    els.transcript.innerHTML = "";
    els.traceList.innerHTML = "";
    resetSessionTotals();
    setStatus("ok", "Ready");
    els.input.focus();
  });

  els.toggleTrace.addEventListener("click", () => {
    const shown = els.trace.hidden;
    els.trace.hidden = !shown;
    els.toggleTrace.setAttribute("aria-pressed", shown ? "true" : "false");
  });

  els.clearTrace.addEventListener("click", () => {
    els.traceList.innerHTML = "";
  });

  loadHealth();
  loadModels();
  loadAgents();
  els.input.focus();
})();
