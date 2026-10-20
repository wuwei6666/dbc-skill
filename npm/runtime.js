import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const root = fileURLToPath(new URL('../', import.meta.url));
export const environment = process.env.DBC_SKILL_VENV || path.join(homedir(), '.dbc-skill', 'venv-v1');
const venvPython = path.join(environment, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');

export function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { shell: false, ...options });
    let stdout = '', stderr = '';
    child.stdout?.on('data', data => { stdout += data; });
    child.stderr?.on('data', data => { stderr += data; });
    child.on('error', reject);
    child.on('close', code => resolve({ code: code ?? 1, stdout, stderr }));
  });
}

export async function python() {
  const candidates = process.env.DBC_SKILL_PYTHON
    ? [[process.env.DBC_SKILL_PYTHON, []]]
    : [...(existsSync(venvPython) ? [[venvPython, []]] : []), ['python3', []], ['python', []], ...(process.platform === 'win32' ? [['py', ['-3']]] : [])];
  for (const [command, prefix] of candidates) {
    try {
      const result = await run(command, [...prefix, '-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)']);
      if (result.code === 0) return { command, prefix };
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
  throw new Error('Python 3.9+ is required by cantools 40.7.1. Install Python, then run: npx dsh-plugin-dbc setup');
}

export async function setup() {
  const selected = await python();
  if (!existsSync(venvPython)) {
    const created = await run(selected.command, [...selected.prefix, '-m', 'venv', environment], { stdio: 'inherit' });
    if (created.code) return created.code;
  }
  const installed = await run(venvPython, ['-m', 'pip', 'install', '-r', path.join(root, 'requirements.txt')], { stdio: 'inherit' });
  return installed.code;
}

export async function execute(args, options = {}) {
  if (!Array.isArray(args) || args.some(arg => typeof arg !== 'string')) throw new Error('Arguments must be an array of strings.');
  const selected = await python();
  const check = await run(selected.command, [...selected.prefix, '-c', "import importlib.metadata as m; assert m.version('cantools') == '40.7.1'; assert m.version('openpyxl') == '3.1.5'"]);
  if (check.code) throw new Error('Required Python dependencies are missing or have different versions. Run: npx dsh-plugin-dbc setup');
  return run(selected.command, [...selected.prefix, path.join(root, 'scripts/dbc_crud.py'), ...args], options);
}
