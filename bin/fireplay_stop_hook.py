"""Continue a bound Fireplay producer once when actionable delivery work remains."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def decision(event, root=ROOT):
    if event.get('hook_event_name') != 'Stop' or event.get('stop_hook_active') is not False:
        return {}
    owner = event.get('session_id')
    if not isinstance(owner, str) or not owner or event.get('permission_mode') == 'plan':
        return {}
    from video_localizer.fireplay import continuous_execution_instruction
    from video_localizer.fireplay_monitor import followups

    if not continuous_execution_instruction(root):
        return {}
    tasks = [task for task in followups(root, owner_thread_id=owner)
             if task['threadId'] == owner and task['action'] != 'await_manual_repair']
    if not tasks:
        return {}
    pending = '；'.join(
        f'{task["code"]} 原片{task["video_index"]}：{task["action"]}，待交语种'
        f'{", ".join(task["missing_locales"]) or "仅待整单核验"}'
        for task in tasks)
    return {
        'decision': 'block',
        'reason': (
            f'项目真实交付记录仍有待办：{pending}。请调用实际工具核对当前缺口、'
            '已有模型任务及可提交成片，并继续执行最靠前的可行操作。普通故障自行换路或修复，'
            '可并行的语种继续，已合格成片先提交。沿原授权、原预算、质量限制及未知操作对账执行。'
            '若用户明确要求暂停、宿主待审批，或全部待办确实已无可行操作，'
            '如实记录具体阻塞后结束。本次结束检查最多自动续一次。'
        )
    }


def main():
    try:
        result = decision(json.load(sys.stdin))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Fireplay stop check unavailable: {type(error).__name__}', file=sys.stderr)
        result = {}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
