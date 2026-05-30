#!/usr/bin/env python3
"""Swarm Health Heartbeat — collects status across all automation and writes to JSON."""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Configuration
DASHBOARD_DIR = Path(__file__).parent.parent
DATA_DIR = DASHBOARD_DIR / 'data'
HEALTH_FILE = DATA_DIR / 'health-status.json'
HERMES_CRON_JOBS = Path.home() / '.hermes/profiles/implementor/cron/jobs.json'

# Dashboard endpoints to ping
DASHBOARD_ENDPOINTS = [
    {'name': 'Swarm Dashboard', 'url': 'http://127.0.0.1:8765/api/status'},
]

# LaunchAgents to monitor
LAUNCH_AGENTS = [
    {'label': 'ai.hermes.gateway-implementor', 'name': 'Hermes Gateway (Implementor)'},
    {'label': 'ai.hermes.gateway', 'name': 'Hermes Gateway (Orchestrator)'},
    {'label': 'com.joshswarm.grocery-capture', 'name': 'Grocery Capture'},
]

# Cron job expected frequencies (in minutes) — used for staleness detection
CRON_EXPECTED_FREQ = {
    'a01b5d3ad0cf': 1440,       # Research Digest — daily
    'aba22b44b38c': 240,        # Polymarket Monitor — every 4h
    '3c33eb37be9e': 180,        # HN Top Stories — every 3h
    '26cdd7120452': 1440,       # Grocery Failure Alert — daily
    '58fe1ed8bde0': 10080,      # Weekly Grocery Differential — weekly
    '7368fd7e9303': 1440,       # Grocery Self-Heal — daily
    '6a9bb079e873': 10080,      # Weekly Grocery Trend — weekly
    '1927dbd91447': 1440,       # Daily Research Topics — daily
}


def get_cron_jobs():
    """Read cron job status from the local jobs.json file."""
    try:
        if not HERMES_CRON_JOBS.exists():
            return []
        data = json.loads(HERMES_CRON_JOBS.read_text(encoding='utf-8'))
        jobs = data.get('jobs', [])
        # Normalize to the format expected by the rest of the script
        normalized = []
        for job in jobs:
            normalized.append({
                'job_id': job.get('id', ''),
                'name': job.get('name', ''),
                'enabled': job.get('enabled', True),
                'last_status': job.get('last_status', 'unknown'),
                'last_run_at': job.get('last_run_at'),
                'next_run_at': job.get('next_run_at'),
                'schedule': job.get('schedule_display', job.get('schedule', {}).get('display', '')),
                'last_error': job.get('last_error'),
            })
        return normalized
    except Exception as e:
        return [{'job_id': 'error', 'name': 'Error reading jobs', 'last_status': 'error', 'error': str(e)}]


def check_launch_agents():
    """Check if LaunchAgents are running via launchctl."""
    results = []
    for la in LAUNCH_AGENTS:
        try:
            result = subprocess.run(
                ['launchctl', 'list', la['label']],
                capture_output=True, text=True, timeout=5
            )
            output = result.stdout.strip()
            # launchctl list returns a plist dict format when service is loaded
            # Running services have "PID" = <positive_int>
            # Stopped services have "LastExitStatus" but no PID
            # Unloaded services produce an error
            is_running = False
            pid = None
            if result.returncode == 0 and output:
                # Parse the plist output for PID
                for line in output.split('\n'):
                    line = line.strip()
                    if line.startswith('"PID"'):
                        try:
                            pid_val = int(line.split('=')[1].strip().rstrip(';'))
                            if pid_val > 0:
                                is_running = True
                                pid = pid_val
                        except (ValueError, IndexError):
                            pass
            elif result.returncode != 0:
                # Service not loaded
                is_running = False
                pid = None

            results.append({
                'label': la['label'],
                'name': la['name'],
                'running': is_running,
                'pid': pid,
                'loaded': result.returncode == 0,
            })
        except Exception as e:
            results.append({
                'label': la['label'],
                'name': la['name'],
                'running': False,
                'pid': None,
                'error': str(e),
            })
    return results


def check_dashboard_endpoints():
    """Ping dashboard endpoints and check response times."""
    results = []
    for ep in DASHBOARD_ENDPOINTS:
        try:
            import urllib.request
            start = time.time()
            req = urllib.request.Request(ep['url'])
            with urllib.request.urlopen(req, timeout=5) as resp:
                elapsed = (time.time() - start) * 1000
                status_code = resp.status
                body = resp.read()
                results.append({
                    'name': ep['name'],
                    'url': ep['url'],
                    'reachable': True,
                    'status_code': status_code,
                    'response_time_ms': round(elapsed, 1),
                    'body_size': len(body),
                })
        except Exception as e:
            results.append({
                'name': ep['name'],
                'url': ep['url'],
                'reachable': False,
                'error': str(e),
            })
    return results


def detect_output_anomalies(cron_jobs):
    """Detect jobs that produce unusually small or empty output (silent failures)."""
    anomalies = []
    for job in cron_jobs:
        job_id = job.get('job_id', '')
        last_status = job.get('last_status')
        if last_status != 'ok':
            continue

        job_name = job.get('name', '')
        output_patterns = {
            'Research Digest': DATA_DIR / 'research-digest-latest.md',
            'Hacker News': DATA_DIR / 'hn-latest.md',
            'Polymarket': DATA_DIR / 'polymarket-latest.md',
        }

        for pattern_name, filepath in output_patterns.items():
            if pattern_name.lower() in job_name.lower() and filepath.exists():
                size = filepath.stat().st_size
                if size < 100:
                    anomalies.append({
                        'job_id': job_id,
                        'job_name': job_name,
                        'type': 'empty_output',
                        'output_size': size,
                        'threshold': 100,
                        'message': f'Job produced only {size} bytes (expected >100)',
                    })
                elif size > 50000:
                    anomalies.append({
                        'job_id': job_id,
                        'job_name': job_name,
                        'type': 'oversized_output',
                        'output_size': size,
                        'threshold': 50000,
                        'message': f'Job produced {size} bytes (expected <50KB)',
                    })
    return anomalies


def compute_overall_health(cron_jobs, launch_agents, endpoints, anomalies):
    """Compute overall health score: healthy, degraded, or critical."""
    issues = []

    for job in cron_jobs:
        job_id = job.get('job_id', '')
        last_status = job.get('last_status')
        last_run = job.get('last_run_at')
        name = job.get('name', '')

        if last_status == 'error':
            issues.append(f'FAILED: {name}')

        if last_run and last_status == 'ok':
            expected_freq = CRON_EXPECTED_FREQ.get(job_id, 360)
            try:
                last_run_dt = datetime.fromisoformat(last_run)
                now = datetime.now(last_run_dt.tzinfo)
                hours_since = (now - last_run_dt).total_seconds() / 3600
                if hours_since > expected_freq / 60 * 1.5:
                    issues.append(f'STALE: {name} ({hours_since:.1f}h since last run, expected every {expected_freq/60}h)')
            except (ValueError, TypeError):
                pass

    for la in launch_agents:
        if not la.get('running'):
            issues.append(f'DOWN: {la["name"]}')

    for ep in endpoints:
        if not ep.get('reachable'):
            issues.append(f'UNREACHABLE: {ep["name"]}')

    for a in anomalies:
        issues.append(f'ANOMALY: {a["job_name"]} — {a["message"]}')

    if not issues:
        return 'healthy', []
    elif len(issues) <= 2:
        return 'degraded', issues
    else:
        return 'critical', issues


def main():
    """Run the heartbeat check and write results."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f'[{datetime.now().isoformat()}] Running heartbeat check...')

    cron_jobs = get_cron_jobs()
    launch_agents = check_launch_agents()
    endpoints = check_dashboard_endpoints()
    anomalies = detect_output_anomalies(cron_jobs)

    overall, issues = compute_overall_health(cron_jobs, launch_agents, endpoints, anomalies)

    result = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'epoch': int(time.time()),
        'overall': overall,
        'issues': issues,
        'cron_jobs': {
            job.get('job_id', ''): {
                'name': job.get('name', ''),
                'enabled': job.get('enabled', True),
                'last_status': job.get('last_status', 'unknown'),
                'last_run': job.get('last_run_at'),
                'next_run': job.get('next_run_at'),
                'schedule': job.get('schedule', ''),
            }
            for job in cron_jobs
        },
        'launch_agents': launch_agents,
        'endpoints': endpoints,
        'anomalies': anomalies,
        'summary': {
            'total_cron': len(cron_jobs),
            'healthy_cron': len([j for j in cron_jobs if j.get('last_status') == 'ok']),
            'failed_cron': len([j for j in cron_jobs if j.get('last_status') == 'error']),
            'running_agents': len([la for la in launch_agents if la.get('running')]),
            'total_agents': len(launch_agents),
            'reachable_endpoints': len([ep for ep in endpoints if ep.get('reachable')]),
            'total_endpoints': len(endpoints),
            'anomaly_count': len(anomalies),
        }
    }

    HEALTH_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')

    print(f'  Overall: {overall.upper()}')
    print(f'  Cron: {result["summary"]["healthy_cron"]}/{result["summary"]["total_cron"]} healthy')
    print(f'  LaunchAgents: {result["summary"]["running_agents"]}/{result["summary"]["total_agents"]} running')
    print(f'  Endpoints: {result["summary"]["reachable_endpoints"]}/{result["summary"]["total_endpoints"]} reachable')
    print(f'  Anomalies: {result["summary"]["anomaly_count"]}')
    if issues:
        print(f'  Issues ({len(issues)}):')
        for issue in issues:
            print(f'    - {issue}')
    print(f'  Written to: {HEALTH_FILE}')

    if overall == 'critical':
        return 2
    elif overall == 'degraded':
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
