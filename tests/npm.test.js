import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { apply } from '../npm/index.js';
import { execute, root, run } from '../npm/runtime.js';

test('Harness registers a validated tool and asks before host execution', async () => {
  let tool, policy;
  apply({ on(event, listener) { assert.equal(event, 'tools/pre-execute'); policy = listener; }, tools: { register(value) { tool = value; } } });
  assert.equal(tool.name, 'dbc');
  assert.equal((await policy({name: 'dbc'}, async () => ({kind:'allow'}))).kind, 'ask');
  assert.equal((await policy({name: 'dbc'}, async () => ({kind:'deny', reason:'blocked'}))).kind, 'deny');
  assert.equal((await policy({name: 'other'}, async () => ({kind:'allow'}))).kind, 'allow');
});

test('CLI wrapper round trips DBC through Excel from an unrelated directory', async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'dbc-npm-test-'));
  try {
    const input = path.join(root, 'examples/example.dbc');
    const workbook = path.join(directory, 'with space.xlsx');
    const output = path.join(directory, 'roundtrip.dbc');
    for (const args of [['excel','export',input,workbook], ['excel','import',workbook,output], ['compare',input,output]]) {
      const result = await execute(['--json', ...args], {cwd:directory});
      assert.equal(result.code, 0, result.stdout + result.stderr);
      const payload = JSON.parse(result.stdout);
      assert.equal(payload.success, true);
      if (args[0] === 'compare') assert.equal(payload.result.equal, true);
    }
    const invalid = await execute(['--json','summary',path.join(directory,'missing.dbc')]);
    assert.equal(invalid.code, 1);
    assert.equal(JSON.parse(invalid.stdout).success, false);
    const cli = await run(process.execPath, [path.join(root,'bin/dbc-skill.js'),'--help'], {cwd:directory});
    assert.equal(cli.code, 0, cli.stderr);
    assert.match(cli.stdout, /excel/);
  } finally { await rm(directory, {recursive:true, force:true}); }
});
