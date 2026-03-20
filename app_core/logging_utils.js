import fs from 'node:fs';
import { LOG_PATH } from './constants.js';

export function log(message) {
  const line = `${new Date().toISOString()} ${message}\n`;
  fs.appendFileSync(LOG_PATH, line, 'utf8');
}
