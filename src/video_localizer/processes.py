"""Bound optional renderer subprocesses, including browser descendants on timeout."""
import os
import signal
import subprocess

from .common import WorkflowError


def run_bounded(args, timeout):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding='utf-8', errors='replace',
                               start_new_session=os.name != 'nt',
                               creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if os.name == 'nt':
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15)
        else:
            os.killpg(process.pid,signal.SIGKILL)
        process.communicate()
        raise WorkflowError('Remotion render timed out; renderer process tree terminated') from exc
    if process.returncode:
        # Do not send external logs into prompts; evidence stays on the local task.
        raise WorkflowError('Remotion render failed: ' + output[-2000:])
    return output
