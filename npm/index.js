import { defineTool } from '@deepseek-ai/dsh-tools';
import { execute } from './runtime.js';

export const name = 'dbc-skill';
export const inject = ['tools'];

export function apply(ctx) {
  // This tool runs on the host, outside any agent shell sandbox. Ask the user
  // through Harness's approval channel; preserve an upstream denial or ask.
  ctx.on('tools/pre-execute', async (call, next) => {
    const decision = await next();
    if (call.name !== 'dbc' || decision.kind !== 'allow') return decision;
    return { kind: 'ask', reason: `Run DBC CLI on the host with arguments ${JSON.stringify(call.arguments)}. Commands can read or replace local files.` };
  });
  ctx.tools.register(defineTool({
    name: 'dbc',
    description: 'Create, inspect, edit, validate or compare CAN/CAN FD DBC files and convert DBC/Excel .xlsx. Pass CLI arguments as separate strings, excluding python and script name. JSON output is automatic. Use absolute file paths. Examples: ["summary","/path/input.dbc"], ["excel","export","/path/input.dbc","/path/output.xlsx"]. For syntax use ["--help"] or ["signal","add","--help"]. In-place edits create .bak; prefer --output for safe edits. Requires the user to run npx dsh-plugin-dbc setup once.',
    parameters: {
      args: { type: 'array', items: { type: 'string' }, required: true, description: 'DBC CLI argument tokens. No shell quoting or shell commands.' },
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    async execute({ args }, call) {
      const result = await execute(['--json', ...args], { signal: call?.signal });
      if (result.code) throw new Error(result.stdout || result.stderr || `DBC CLI exited ${result.code}`);
      return result.stdout;
    },
  }));
}
