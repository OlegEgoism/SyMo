import os from 'node:os';
import path from 'node:path';

export const APP_NAME = 'SyMo';
export const UPDATE_INTERVAL_MS = 1000;
export const NOTIFICATION_INTERVAL_MIN = 30;

export const CONFIG_DIR = path.join(os.homedir(), '.config', 'symo');
export const CONFIG_PATH = path.join(CONFIG_DIR, 'config.json');
export const LOG_PATH = path.join(CONFIG_DIR, 'symo.log');

export const DEFAULT_CONFIG = {
  language: 'en',
  notificationIntervalMin: NOTIFICATION_INTERVAL_MIN,
  telegram: {
    enabled: false,
    botToken: '',
    chatId: ''
  },
  discord: {
    enabled: false,
    webhookUrl: ''
  },
  menu: {
    cpu: true,
    ram: true,
    swap: true,
    disk: true,
    network: true,
    uptime: true,
    keyboard: true,
    mouse: true
  }
};
