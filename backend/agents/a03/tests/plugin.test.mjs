import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

test("installed pi-web-access exposes the pinned MCP search and read contracts without credentials", async () => {
  const directory = await mkdtemp(join(tmpdir(), "a03-plugin-test-"));
  await writeFile(join(directory, "web-search.json"), JSON.stringify({
    webSearch: { enabled: false }, autoOpenBrowser: false,
    fetchContent: { redirects: "same-origin", domainPolicy: { allow: ["example.com"] } },
    fetchRouting: { allowRemoteHostedProviders: false },
  }));
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [fileURLToPath(new URL("../node_modules/pi-web-access/dist/mcp-cli.js", import.meta.url))],
    env: { PATH: process.env.PATH ?? "", SystemRoot: process.env.SystemRoot ?? "",
      TEMP: directory, TMP: directory, PI_CODING_AGENT_DIR: directory },
    stderr: "ignore",
  });
  const client = new Client({ name: "a03-contract-test", version: "1.0.0" });
  try {
    await client.connect(transport);
    const tools = (await client.listTools()).tools;
    const fetch = tools.find((tool) => tool.name === "fetch_content");
    assert.ok(fetch?.inputSchema.properties.url);
    // This is an invalid argument check, so no search, page request or credentials are used.
    const result = await client.callTool({ name: "fetch_content", arguments: { url: 42 } });
    assert.equal(result.isError, true);
  } finally {
    await client.close();
    await transport.close();
    await rm(directory, { recursive: true, force: true });
  }
});
