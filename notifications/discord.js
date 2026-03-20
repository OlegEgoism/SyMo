import axios from 'axios';

export class DiscordNotifier {
  constructor(config) {
    this.config = config;
    this.lastSentAt = 0;
  }

  async sendStatus(message) {
    if (!this.config?.enabled || !this.config.webhookUrl) return;
    const now = Date.now();
    if (now - this.lastSentAt < 30 * 60 * 1000) return;

    await axios.post(this.config.webhookUrl, { content: message });
    this.lastSentAt = now;
  }
}
