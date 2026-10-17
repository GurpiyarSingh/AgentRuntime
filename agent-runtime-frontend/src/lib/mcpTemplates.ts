/**
 * Starting points for popular MCP servers, and the empty config they fill.
 * Placeholders in angle brackets (`<...>`) are for the user to replace.
 */

import type { McpServerConfig } from '../api/types';
import type { IconName } from '../components/Icon';
import type { Tone } from './toolMeta';

export interface McpTemplate {
  id: string;
  /** Suggested server name (it prefixes the tools: `github__...`). */
  name: string;
  title: string;
  icon: IconName;
  tone: Tone;
  /** What to fill in, and what the server needs. */
  hint: string;
  config: Partial<McpServerConfig>;
}

export function emptyConfig(): McpServerConfig {
  return {
    type: 'stdio',
    command: '',
    args: [],
    env: {},
    cwd: null,
    url: '',
    headers: {},
    enabled: true,
    timeout_s: 60,
    description: '',
  };
}

export const MCP_TEMPLATES: McpTemplate[] = [
  {
    id: 'github',
    name: 'github',
    title: 'GitHub',
    icon: 'code',
    tone: 'violet',
    hint: "GitHub's hosted server. Replace <token> with a personal access token from github.com/settings/tokens.",
    config: {
      type: 'http',
      url: 'https://api.githubcopilot.com/mcp/',
      headers: { Authorization: 'Bearer <token>' },
      description: 'Issues, pull requests, code and repositories on GitHub.',
    },
  },
  {
    id: 'playwright',
    name: 'playwright',
    title: 'Playwright',
    icon: 'globe',
    tone: 'green',
    hint: 'Browses the web in a real browser. Needs Node.js (npx) on the server; the first start downloads the browser, so allow a few minutes.',
    config: {
      type: 'stdio',
      command: 'npx',
      args: ['@playwright/mcp@latest', '--headless'],
      timeout_s: 180,
      description: 'Open pages, click, fill forms and take screenshots.',
    },
  },
  {
    id: 'jira',
    name: 'jira',
    title: 'Jira & Confluence',
    icon: 'layers',
    tone: 'blue',
    hint: 'The mcp-atlassian server. Needs uv (uvx) on the server. Create an API token at id.atlassian.com → Security → API tokens.',
    config: {
      type: 'stdio',
      command: 'uvx',
      args: ['mcp-atlassian'],
      env: {
        JIRA_URL: 'https://<your-company>.atlassian.net',
        JIRA_USERNAME: '<you@company.com>',
        JIRA_API_TOKEN: '<api-token>',
      },
      timeout_s: 120,
      description: 'Search, create and update Jira issues and Confluence pages.',
    },
  },
  {
    id: 'filesystem',
    name: 'filesystem',
    title: 'Filesystem',
    icon: 'folder',
    tone: 'amber',
    hint: 'Gives the agent another folder. Replace <folder> with an absolute path on the server. Needs Node.js (npx).',
    config: {
      type: 'stdio',
      command: 'npx',
      args: ['-y', '@modelcontextprotocol/server-filesystem', '<folder>'],
      description: 'Read and write files in a folder of your choice.',
    },
  },
  {
    id: 'fetch',
    name: 'fetch',
    title: 'Fetch',
    icon: 'download',
    tone: 'cyan',
    hint: 'Fetches web pages as Markdown. Needs uv (uvx) on the server.',
    config: {
      type: 'stdio',
      command: 'uvx',
      args: ['mcp-server-fetch'],
      description: 'Read any web page.',
    },
  },
  {
    id: 'memory',
    name: 'memory',
    title: 'Memory',
    icon: 'sparkles',
    tone: 'pink',
    hint: 'A small knowledge graph the agent can remember things in. Needs Node.js (npx).',
    config: {
      type: 'stdio',
      command: 'npx',
      args: ['-y', '@modelcontextprotocol/server-memory'],
      description: 'Long-term memory across conversations.',
    },
  },
];

/** A full config from a template. */
export function fromTemplate(template: McpTemplate): McpServerConfig {
  return { ...emptyConfig(), ...template.config };
}

export const IMPORT_EXAMPLE = `{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest", "--headless"]
    },
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}`;
