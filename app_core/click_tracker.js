export class ClickTracker {
  constructor() {
    this.keyboard = 0;
    this.mouse = 0;
  }

  registerKeyboard(count = 1) {
    this.keyboard += count;
  }

  registerMouse(count = 1) {
    this.mouse += count;
  }

  snapshot() {
    return {
      keyboard: this.keyboard,
      mouse: this.mouse
    };
  }
}
