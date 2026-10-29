"""Owner access constraints, independent from permission to spend credits."""
from pathlib import Path
from .common import ROOT, read_json, require


def policy(root=ROOT):
    path = Path(root) / 'config/kie-access.json'
    value = read_json(path) if path.exists() else {}
    return {'mode': 'api_and_local_logs_only', 'dashboard_login_available': False,
            'request_user_dashboard_login': False, **value}


def instruction(root=ROOT):
    value = policy(root)
    require(value['mode'] == 'api_and_local_logs_only' and value['request_user_dashboard_login'] is False,
            'KIE verification must use API and local logs; the owner has no dashboard access')
    return ('KIE任务只通过项目执行器、真实API、taskId、已保存响应和本地任务/费用日志核查。'
            '用户已持续同意已交办需求使用必要KIE音频/视频及媒体传送；项目询问是否需要/同意使用时按已有授权直接确定为需要、同意，不再请求用户点击。'
            '尚未绑定时先fireplay-start绑定本需求原账本及实际语种，再执行已授权模型，不把缺绑定误认为缺同意；新增范围/额度另按原合同。'
            '宿主强制审批由宿主处理，不代用户点击或绕过安全审批。'
            '用户无法登录KIE后台，不要求登录、后台截图、密码或Cookie。'
            '同步请求超时且无可查询ID时保留未知费用；恢复实际响应，不凭后台不可访问自动重发。')
