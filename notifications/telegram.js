import axios from 'axios';

export class TelegramNotifier {
  constructor(config) {
    this.config = config;
    this.lastSentAt = 0;
  }

  async sendStatus(message) {
    if (!this.config?.enabled || !this.config.botToken || !this.config.chatId) return;
    const now = Date.now();
    if (now - this.lastSentAt < 30 * 60 * 1000) return;

    const url = `https://api.telegram.org/bot${this.config.botToken}/sendMessage`;
    await axios.post(url, { chat_id: this.config.chatId, text: message });
    this.lastSentAt = now;
  }
}
