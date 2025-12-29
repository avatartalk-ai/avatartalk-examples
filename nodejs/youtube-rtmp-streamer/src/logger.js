const LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'];

export class Logger {
  constructor(level = 'INFO') {
    this.setLevel(level);
  }
  setLevel(level) {
    const up = String(level || 'INFO').toUpperCase();
    this.levelIndex = Math.max(0, LEVELS.indexOf(up));
    this.level = up;
  }
  shouldLog(level) {
    return LEVELS.indexOf(level) >= this.levelIndex;
  }
  _fmt(level, msg, ...args) {
    const ts = new Date().toISOString();
    return `${ts} ${level} ${msg}`;
  }
  debug(msg, ...args) { if (this.shouldLog('DEBUG')) console.error(this._fmt('DEBUG', msg), ...args); }
  info(msg, ...args) { if (this.shouldLog('INFO')) console.error(this._fmt('INFO', msg), ...args); }
  warn(msg, ...args) { if (this.shouldLog('WARNING')) console.error(this._fmt('WARNING', msg), ...args); }
  error(msg, ...args) { if (this.shouldLog('ERROR')) console.error(this._fmt('ERROR', msg), ...args); }
  critical(msg, ...args) { if (this.shouldLog('CRITICAL')) console.error(this._fmt('CRITICAL', msg), ...args); }
}

