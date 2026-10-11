// npm does not install Python dependencies. Keep the UI in a package-local venv
// so Homebrew / system Python and other projects are left untouched.
const { spawnSync } = require('node:child_process');
const { join } = require('node:path');

const root = join(__dirname, '..');
const python = process.env.NOVANODE_PYTHON || 'python3';
const venv = join(root, '.novanode-venv');
const pip = join(venv, 'bin', 'python3');

function run(program, args) {
  const result = spawnSync(program, args, { stdio: 'inherit' });
  if (result.error) {
    console.error(`NovaNode UI setup: ${result.error.message}`);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status || 1);
}

run(python, ['-m', 'venv', venv]);
run(pip, ['-m', 'pip', '--disable-pip-version-check', 'install', 'textual==8.2.8']);
