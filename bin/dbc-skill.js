#!/usr/bin/env node
import { execute, setup } from '../npm/runtime.js';
const args = process.argv.slice(2);
try {
  if (args[0] === 'setup') {
    if (args.length !== 1) throw new Error('Usage: dbc-skill setup');
    process.exitCode = await setup();
  } else {
    process.exitCode = (await execute(args, { stdio: 'inherit' })).code;
  }
} catch (error) {
  console.error(`dbc-skill: ${error.message}`);
  process.exitCode = 1;
}
