import si from 'systeminformation';

export class SystemUsage {
  constructor() {
    this.lastNetwork = { rx: 0, tx: 0, ts: Date.now() };
  }

  async snapshot() {
    const [load, temp, mem, fs, net, uptime] = await Promise.all([
      si.currentLoad(),
      si.cpuTemperature(),
      si.mem(),
      si.fsSize(),
      si.networkStats(),
      si.time()
    ]);

    const totalRx = net.reduce((sum, item) => sum + item.rx_bytes, 0);
    const totalTx = net.reduce((sum, item) => sum + item.tx_bytes, 0);
    const now = Date.now();
    const diffSec = Math.max((now - this.lastNetwork.ts) / 1000, 1);
    const down = Math.max((totalRx - this.lastNetwork.rx) / diffSec, 0);
    const up = Math.max((totalTx - this.lastNetwork.tx) / diffSec, 0);

    this.lastNetwork = { rx: totalRx, tx: totalTx, ts: now };

    return {
      cpu: Number(load.currentLoad.toFixed(1)),
      cpuTemp: temp.main ? Number(temp.main.toFixed(1)) : null,
      ramPercent: Number(((mem.active / mem.total) * 100).toFixed(1)),
      swapPercent: mem.swaptotal > 0 ? Number(((mem.swapused / mem.swaptotal) * 100).toFixed(1)) : 0,
      diskPercent: fs.length ? Number(fs.reduce((acc, d) => acc + d.use, 0) / fs.length).toFixed(1) : 0,
      downBytesSec: down,
      upBytesSec: up,
      uptimeSec: uptime.uptime
    };
  }
}
