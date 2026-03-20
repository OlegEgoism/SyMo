import fs from 'node:fs';
import path from 'node:path';
import { DEFAULT_CONFIG, CONFIG_DIR, CONFIG_PATH, UPDATE_INTERVAL_MS } from './constants.js';
import { Localization } from './localization.js';
import { SystemUsage } from './system_usage.js';
import { ClickTracker } from './click_tracker.js';
import { TelegramNotifier } from '../notifications/telegram.js';
import { DiscordNotifier } from '../notifications/discord.js';
import { log } from './logging_utils.js';

function formatBytesPerSec(value) {
  if (value > 1024 * 1024) return `${(value / 1024 / 1024).toFixed(2)} MB/s`;
  if (value > 1024) return `${(value / 1024).toFixed(2)} KB/s`;
  return `${value.toFixed(0)} B/s`;
}

function ensureConfig() {
  fs.mkdirSync(CONFIG_DIR, { recursive: true });
  if (!fs.existsSync(CONFIG_PATH)) {
    fs.writeFileSync(CONFIG_PATH, `${JSON.stringify(DEFAULT_CONFIG, null, 2)}\n`, 'utf8');
  }
  const raw = fs.readFileSync(CONFIG_PATH, 'utf8');
  return { ...DEFAULT_CONFIG, ...JSON.parse(raw) };
}

export class SyMoApp {
  constructor() {
    this.config = ensureConfig();
    this.i18n = new Localization(this.config.language);
    this.system = new SystemUsage();
    this.clicks = new ClickTracker();
    this.telegram = new TelegramNotifier(this.config.telegram);
    this.discord = new DiscordNotifier(this.config.discord);
  }

  async tick() {
    const metrics = await this.system.snapshot();
    const clickSnapshot = this.clicks.snapshot();

    const line = [
      `${this.i18n.t('cpu')}: ${metrics.cpu}%`,
      `${this.i18n.t('ram')}: ${metrics.ramPercent}%`,
      `${this.i18n.t('disk')}: ${metrics.diskPercent}%`,
      `${this.i18n.t('network')} ↓ ${formatBytesPerSec(metrics.downBytesSec)} ↑ ${formatBytesPerSec(metrics.upBytesSec)}`,
      `${this.i18n.t('keyboard')}: ${clickSnapshot.keyboard}`,
      `${this.i18n.t('mouse')}: ${clickSnapshot.mouse}`
    ].join(' | ');

    console.log(line);
    log(line);

    await Promise.all([
      this.telegram.sendStatus(line),
      this.discord.sendStatus(line)
    ]);
  }

  start() {
    console.log(this.i18n.t('appTitle'));
    this.tick().catch((err) => console.error(err));
    setInterval(() => this.tick().catch((err) => console.error(err)), UPDATE_INTERVAL_MS);
  }
}
