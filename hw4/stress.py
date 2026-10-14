import argparse
from collections import Counter, deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import threading
import time

from monitor import snapshot, wait_until


def stop_process(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def run_stage(args, clients, out):
    stop = threading.Event()
    processes, lock = {}, threading.Lock()
    results = [None] * clients

    def worker(index):
        stats = {'client': index + 1, 'status_counts': {}, 'unexpected_exits': 0,
                 'request_lines': 0, 'launches': 0, 'error_samples': [],
                 'requests_without_status': 0, 'error_lines': 0}
        counts = Counter()
        path = None
        with (out / f'clients-{clients}-worker-{index + 1}.jsonl').open('w') as handle:
            while not stop.is_set():
                command = [str(Path(args.client).resolve()), '-d', args.host, '-p', str(args.port),
                           '-b', 'none', '-w', 'pages', '-n', '1000000', '-i', '11999',
                           '-r', str(528000 + clients * 10 + index), '-t', '20', '-v']
                with lock:
                    if stop.is_set():
                        break
                    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                               stderr=subprocess.STDOUT, text=True,
                                               errors='replace', start_new_session=True,
                                               env={**os.environ, 'PYTHONUNBUFFERED': '1'})
                    processes[index] = process
                stats['launches'] += 1
                tail = deque(maxlen=12)
                for line in process.stdout:
                    request = re.match(r'^Requesting\s+(\S+)', line)
                    status = re.match(r'^(\d{3})\s+', line)
                    if request:
                        if path is not None:
                            stats['requests_without_status'] += 1
                            handle.write(json.dumps({'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                                                     'path': path, 'event': 'request_without_status'}) + '\n')
                        path = request.group(1)
                        stats['request_lines'] += 1
                    elif status:
                        counts[status.group(1)] += 1
                        handle.write(json.dumps({'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                                                 'path': path, 'status': int(status.group(1))}) + '\n')
                        handle.flush()
                        path = None
                    elif not line.startswith(("b'", 'b"')) and line.strip():
                        tail.append(line.rstrip()[:1000])
                        if re.search(r'Traceback|Error|timed out|refused|reset', line, re.I):
                            stats['error_lines'] += 1
                            handle.write(json.dumps({'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                                                     'event': 'client_error_output',
                                                     'message': line.rstrip()[:1000]}) + '\n')
                            handle.flush()
                code = process.wait()
                process.stdout.close()
                with lock:
                    processes.pop(index, None)
                if not stop.is_set():
                    if path is not None:
                        stats['requests_without_status'] += 1
                        path = None
                    stats['unexpected_exits'] += 1
                    if len(stats['error_samples']) < 10:
                        stats['error_samples'].append({'exit_code': code, 'tail': list(tail)})
                    # The old process has exited before this worker starts a replacement.
                    stop.wait(0.2)
        stats['status_counts'] = dict(counts)
        results[index] = stats

    before = snapshot('none')
    started = datetime.now(timezone.utc).isoformat()
    deadline = time.monotonic() + args.duration
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(clients)]
    try:
        for thread in threads:
            thread.start()
        stop.wait(max(0, deadline - time.monotonic()))
    finally:
        stop.set()
        with lock:
            for process in list(processes.values()):
                stop_process(process)
        for thread in threads:
            if thread.ident is not None:
                thread.join()
    if any(result is None for result in results):
        raise RuntimeError('A client worker failed; the stage is not valid.')
    after = snapshot('none')
    cpu_delta = [b - a for a, b in zip(before['cpu'], after['cpu'])]
    totals = Counter()
    for result in results:
        totals.update(result['status_counts'])
    summary = {
        'clients': clients, 'planned_duration_s': args.duration,
        'started_utc': started, 'finished_utc': datetime.now(timezone.utc).isoformat(),
        'status_counts': dict(totals), 'successful_responses_per_s': totals['200'] / args.duration,
        'permission_denied_400': totals['400'],
        'unexpected_exits': sum(r['unexpected_exits'] for r in results),
        'requests_without_status': sum(r['requests_without_status'] for r in results),
        'error_lines': sum(r['error_lines'] for r in results),
        'client_vm_cpu_busy_pct_mean': 100 * sum(cpu_delta[i] for i in (0, 1, 2, 5, 6)) / sum(cpu_delta),
        'client_vm_memory_used_pct_end': 100 * (after['memory']['MemTotal'] - after['memory']['MemAvailable']) / after['memory']['MemTotal'],
        'workers': results,
        'boundary_note': 'Processes are deliberately terminated at the deadline; partial final requests and these exits are not overload failures.',
    }
    (out / f'clients-{clients}-summary.json').write_text(json.dumps(summary, indent=2))
    print(f'{clients} clients: statuses={dict(totals)}, unexpected exits={summary["unexpected_exits"]}', flush=True)


def main(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'experiment.json').write_text(json.dumps({
        'hostname': socket.gethostname(), 'server_ip': args.host,
        'scheduled_start_epoch': args.start_at, 'duration_s': args.duration,
        'cooldown_s': args.cooldown, 'stages': args.stages,
    }, indent=2))
    base = time.monotonic() + args.start_at - time.time()
    for index, clients in enumerate(args.stages):
        start = base + index * (args.duration + args.cooldown)
        if time.monotonic() > start + 1:
            raise RuntimeError('Missed scheduled stage start; choose a later start time.')
        wait_until(start)
        run_stage(args, clients, out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-at', type=float, required=True)
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--client', default='./http-client')
    parser.add_argument('--duration', type=int, default=180)
    parser.add_argument('--cooldown', type=int, default=15)
    parser.add_argument('--stages', type=int, nargs='+', default=[1, 2, 3, 4], choices=[1, 2, 3, 4])
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    if args.duration < 1 or args.cooldown < 0:
        parser.error('duration must be positive and cooldown nonnegative')
    main(args)
