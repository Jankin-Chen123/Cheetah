/** Pi owns the reasoning/tool loop. The Python host owns authorization, evidence and effects. */
import { Agent, type AgentMessage, type AgentTool } from "@earendil-works/pi-agent-core";
import { createAssistantMessageEventStream, type AssistantMessage, type Model } from "@earendil-works/pi-ai";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { createHash } from "node:crypto";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

type Json = Record<string, any>;
const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
const pending = new Map<string, { resolve: (value: any) => void; reject: (error: Error) => void }>();
let requestNumber = 0;
let started = false;
let plugin: Client | undefined;
let pluginTransport: StdioClientTransport | undefined;

function emit(value: Json): void {
  process.stdout.write(JSON.stringify(value) + "\n");
}

function host(method: string, args: Json): Promise<any> {
  const id = String(++requestNumber);
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    emit({ type: "request", id, method, args });
  });
}

async function pluginCall(command: Json, configDir: string): Promise<unknown> {
  if (!plugin) {
    pluginTransport = new StdioClientTransport({
      command: process.execPath,
      args: [fileURLToPath(new URL("../node_modules/pi-web-access/dist/mcp-cli.js", import.meta.url))],
      env: {
        PATH: process.env.PATH ?? "", SystemRoot: process.env.SystemRoot ?? "",
        TEMP: process.env.TEMP ?? "", TMP: process.env.TMP ?? "",
        PI_CODING_AGENT_DIR: configDir,
      },
      stderr: "ignore",
    });
    plugin = new Client({ name: "cheetah-a03", version: "1.0.0" });
    await plugin.connect(pluginTransport);
  }
  // The model never selects the MCP tool, provider, proxy, or credential directory.
  if (!["web_search", "fetch_content"].includes(command.name)) throw new Error("Plugin tool denied");
  return await plugin.callTool({ name: command.name, arguments: command.arguments }, undefined, {
    timeout: 30000,
  });
}

async function run(packet: Json): Promise<void> {
  let finished = false;
  const tools: AgentTool<any>[] = packet.tools.map((definition: Json) => ({
    name: definition.name,
    label: definition.name,
    description: definition.description,
    parameters: definition.parameters,
    executionMode: "sequential",
    replay: "never",
    execute: async (callId: string, args: Json) => {
      let result = await host("tool", { call_id: callId, name: definition.name, arguments: args });
      if (result.plugin) {
        // The durable intent and budget have already been recorded by the host.
        const response = await pluginCall(result.plugin, packet.plugin_config_dir);
        result = await host("plugin_result", { call_id: callId, result: response });
      }
      if (result.finished) finished = true;
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result) }],
        details: {},
        ...(result.finished ? { terminate: true } : {}),
        ...(result.error ? { isError: true } : {}),
      };
    },
  }));
  const model = {
    id: packet.model_name, name: packet.model_name, api: "openai-completions",
    provider: "cheetah-host", baseUrl: "", reasoning: false, input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 128000, maxTokens: packet.max_output_tokens,
  } as Model<any>;
  const restored = [...packet.messages] as AgentMessage[];
  const latestAssistant = restored.findLastIndex((message) => message.role === "assistant");
  if (latestAssistant >= 0) {
    const message = restored[latestAssistant] as AssistantMessage;
    const completed = new Set(restored.slice(latestAssistant + 1)
      .filter((entry) => entry.role === "toolResult").map((entry) => (entry as any).toolCallId));
    for (const call of message.content.filter((part) => part.type === "toolCall")) {
      if (completed.has(call.id)) continue;
      const tool = tools.find((tool) => tool.name === call.name);
      if (!tool) throw new Error("Restored tool is no longer available");
      const result = await tool.execute(call.id, call.arguments);
      restored.push({ role: "toolResult", toolCallId: call.id, toolName: call.name,
        content: result.content, details: {}, isError: result.isError ?? false, timestamp: Date.now() });
      await host("checkpoint", { messages: restored });
    }
  }
  if (finished) { emit({ type: "done", finished: true }); return; }
  const agent = new Agent({
    initialState: {
      model, systemPrompt: packet.system_prompt, tools,
      ...(restored.length ? { messages: restored } : {}),
    },
    toolExecution: "sequential",
    streamFn: async (_model, context) => {
      const request = { messages: context.messages, tools: packet.tools };
      const key = createHash("sha256").update(JSON.stringify(request)).digest("hex");
      const message = await host("model", { call_id: `model:${key}`, ...request }) as AssistantMessage;
      const stream = createAssistantMessageEventStream();
      if (message.stopReason === "error" || message.stopReason === "aborted") {
        stream.push({ type: "error", reason: message.stopReason, error: message });
      } else if (message.stopReason !== "pending") {
        stream.push({ type: "done", reason: message.stopReason, message });
      } else {
        throw new Error("Pending model responses cannot be treated as final");
      }
      stream.end(message);
      return stream;
    },
    // A model's prose answer is not a valid report: a checked finish tool must commit it.
    finishTurn: async ({ message }) => {
      if (finished) return { action: "end" };
      if (["error", "aborted"].includes(message.stopReason)) return;
      return { action: "continue" };
    },
  });
  agent.subscribe(async (event) => {
    if (event.type === "message_end") await host("checkpoint", { messages: agent.state.messages });
  });
  if (restored.at(-1)?.role === "assistant") {
    await agent.prompt("继续本次已有研究任务，检查剩余目标并通过 finish_research 交付。");
  }
  else if (restored.length) await agent.continue();
  else await agent.prompt(JSON.stringify(packet.input));
  emit({ type: "done", finished, error: agent.state.errorMessage ? "MODEL_TURN_FAILED" : null });
}

input.on("line", (line) => {
  if (Buffer.byteLength(line) > 2_000_000) process.exit(2);
  let packet: Json;
  try { packet = JSON.parse(line); } catch { process.exit(2); }
  if (!started) {
    started = true;
    void run(packet).catch(() => emit({ type: "failed", error: "PI_EXECUTION_FAILED" })).finally(async () => {
      await plugin?.close().catch(() => undefined);
      await pluginTransport?.close().catch(() => undefined);
      input.close();
    });
    return;
  }
  const waiter = pending.get(packet.id);
  if (!waiter) return;
  pending.delete(packet.id);
  if (packet.error) waiter.reject(new Error(packet.error.code ?? "HOST_REQUEST_FAILED"));
  else waiter.resolve(packet.result);
});
input.on("close", () => {
  for (const waiter of pending.values()) waiter.reject(new Error("HOST_DISCONNECTED"));
  pending.clear();
});
