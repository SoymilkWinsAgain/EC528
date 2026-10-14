import argparse
import csv
import os
from pathlib import Path
import subprocess
import time
from datetime import datetime, timezone


def snapshot(service):
    cpu = [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        memory[key] = int(value.split()[0])
    interface = next(
        line.split()[0] for line in Path('/proc/net/route').read_text().splitlines()[1:]
        if line.split()[1] == '00000000'
    )
    network = next(
        line.split(':', 1)[1].split() for line in Path('/proc/net/dev').read_text().splitlines()
        if ':' in line and line.split(':', 1)[0].strip() == interface
    )
    pid, ticks, rss = 0, 0, 0
    if service != 'none':
        result = subprocess.run(
            ['systemctl', 'show', service, '-p', 'MainPID', '--value'],
            capture_output=True, text=True, check=True,
        )
        pid = int(result.stdout.strip() or 0)
        try:
            fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
            ticks = int(fields[11]) + int(fields[12])
            rss = int(fields[21]) * os.sysconf('SC_PAGE_SIZE')
        except FileNotFoundError:
            pid = 0
    return {
        'clock': time.monotonic(), 'cpu': cpu, 'memory': memory,
        'interface': interface, 'rx': int(network[0]), 'tx': int(network[8]),
        'pid': pid, 'ticks': ticks, 'rss': rss,
    }


def wait_until(deadline):
    while time.monotonic() < deadline:
        time.sleep(max(0, min(0.5, deadline - time.monotonic())))


def collect(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    base = time.monotonic() + args.start_at - time.time()
    fields = ['timestamp_utc', 'clients', 'elapsed_s', 'interval_s', 'interface',
              'vm_cpu_busy_pct', 'vm_cpu_steal_pct', 'vm_cpu_iowait_pct',
              'vm_memory_used_mib', 'vm_memory_used_pct',
              'rx_bytes_per_s', 'tx_bytes_per_s', 'total_mbps',
              'service_pid', 'service_cpu_pct_one_core', 'service_rss_mib']
    for stage_index, clients in enumerate(args.stages):
        start = base + stage_index * (args.duration + args.cooldown)
        if time.monotonic() > start + 1:
            raise RuntimeError('Missed scheduled stage start; choose a later start time.')
        wait_until(start)
        previous = snapshot(args.service)
        with (out / f'metrics-{clients}.csv').open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for sample in range(1, args.duration // args.interval + 1):
                wait_until(start + sample * args.interval)
                current = snapshot(args.service)
                elapsed = current['clock'] - previous['clock']
                delta = [b - a for a, b in zip(previous['cpu'], current['cpu'])]
                total = sum(delta)
                # busy excludes idle, iowait, and steal; guest counters are excluded.
                busy = sum(delta[i] for i in (0, 1, 2, 5, 6))
                memory = current['memory']
                used_kib = memory['MemTotal'] - memory['MemAvailable']
                rx = (current['rx'] - previous['rx']) / elapsed
                tx = (current['tx'] - previous['tx']) / elapsed
                same_process = current['pid'] != 0 and current['pid'] == previous['pid']
                process_cpu = ((current['ticks'] - previous['ticks']) /
                               os.sysconf('SC_CLK_TCK') / elapsed * 100) if same_process else ''
                writer.writerow({
                    'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                    'clients': clients, 'elapsed_s': round(current['clock'] - start, 3),
                    'interval_s': round(elapsed, 3), 'interface': current['interface'],
                    'vm_cpu_busy_pct': round(100 * busy / total, 3) if total else '',
                    'vm_cpu_steal_pct': round(100 * delta[7] / total, 3) if total else '',
                    'vm_cpu_iowait_pct': round(100 * delta[4] / total, 3) if total else '',
                    'vm_memory_used_mib': round(used_kib / 1024, 3),
                    'vm_memory_used_pct': round(used_kib / memory['MemTotal'] * 100, 3),
                    'rx_bytes_per_s': round(rx, 3), 'tx_bytes_per_s': round(tx, 3),
                    'total_mbps': round((rx + tx) * 8 / 1_000_000, 6),
                    'service_pid': current['pid'],
                    'service_cpu_pct_one_core': round(process_cpu, 3) if same_process else '',
                    'service_rss_mib': round(current['rss'] / 1024**2, 3),
                })
                handle.flush()
                previous = current
        print(f'Collected {clients}-client stage: {out / f"metrics-{clients}.csv"}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-at', type=float, required=True, help='UTC Unix epoch seconds')
    parser.add_argument('--duration', type=int, default=180)
    parser.add_argument('--cooldown', type=int, default=15)
    parser.add_argument('--interval', type=int, default=5)
    parser.add_argument('--stages', type=int, nargs='+', default=[1, 2, 3, 4], choices=[1, 2, 3, 4])
    parser.add_argument('--service', default='hw4-app.service')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    if args.interval < 1 or args.duration < args.interval or args.duration % args.interval:
        parser.error('duration must be a positive multiple of interval')
    collect(args)
