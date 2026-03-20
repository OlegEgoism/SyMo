import { exec } from 'node:child_process';

function run(cmd) {
  exec(cmd, (error) => {
    if (error) {
      console.error(`[power] ${cmd} failed:`, error.message);
    }
  });
}

export const PowerControl = {
  shutdown(delaySec = 0) {
    run(delaySec > 0 ? `shutdown -h +${Math.ceil(delaySec / 60)}` : 'shutdown now');
  },
  reboot(delaySec = 0) {
    run(delaySec > 0 ? `shutdown -r +${Math.ceil(delaySec / 60)}` : 'reboot');
  },
  lock() {
    run('loginctl lock-session');
  }
};
