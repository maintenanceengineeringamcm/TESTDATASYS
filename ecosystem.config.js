// PM2 process file for the HI system (Windows server).
//
//   pm2 start ecosystem.config.js
//   pm2 save
//
// Two processes: the configuration service (127.0.0.1:5001, never public) and
// the API + built UI (HI_HOST:HI_PORT from backend\.env, reached through IIS at
// /testanalysis). Paths are relative to this file, so the folder can live
// anywhere. Set HI_PYTHON to python.exe's full path if `python` is not on the
// PATH of the account PM2 runs as.
const path = require('path')

const python = process.env.HI_PYTHON || 'python'
const logs = path.join(__dirname, 'backend', 'logs')

const common = {
  interpreter: python,
  autorestart: true,
  watch: false,
  max_restarts: 10,
  restart_delay: 5000,
  windowsHide: true,
  merge_logs: true,
  time: true,
  // Python buffers stdout when it is not a terminal; without this the PM2 log
  // stays empty until the buffer fills.
  env: { PYTHONUNBUFFERED: '1' },
}

module.exports = {
  apps: [
    {
      ...common,
      name: 'hi-config',
      script: 'app.py',
      cwd: path.join(__dirname, 'config-service'),
      out_file: path.join(logs, 'pm2-config.log'),
      error_file: path.join(logs, 'pm2-config.log'),
    },
    {
      ...common,
      name: 'hi-api',
      // serve.py = waitress (multi-threaded). Never app.py here: that is
      // Flask's single-threaded development server.
      script: 'serve.py',
      cwd: path.join(__dirname, 'backend'),
      out_file: path.join(logs, 'pm2-api.log'),
      error_file: path.join(logs, 'pm2-api.log'),
    },
  ],
}
