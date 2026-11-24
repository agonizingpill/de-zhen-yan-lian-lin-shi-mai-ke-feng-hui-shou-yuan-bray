import json
from pathlib import Path
from traceback import print_exc

from core import queueing
from domain.learning import calculate

pulse = Path('/tmp/compute-heartbeat')


def handle_job(item):
    """处理一条计算任务并回写凭证。测试与常驻循环共用这同一段逻辑。"""
    job = json.loads(item)
    # 必须带回 venue，否则凭证完成后会丢失场地归属，导致本场也无法查看/签发。
    status = {'owner': job['owner'], 'venue': job['venue'], 'input': job['input']}
    try:
        status.update(status='ready', result=calculate(job['input']))
    except ValueError as exc:
        status.update(status='rejected', detail=str(exc))
    except Exception:
        print_exc()
        status.update(status='rejected', detail='计算失败，请检查输入和 worker 日志')
    with queueing.broker.pipeline() as pipe:
        pipe.set(f'compute:{job["token"]}', json.dumps(status, allow_nan=False), ex=86400)
        pipe.lrem(f'{queueing.QUEUE}:processing', 1, item)
        pipe.execute()


def serve():
    while True:
        queueing.broker.ping()
        pulse.touch()
        item = queueing.broker.blmove(
            queueing.QUEUE, f'{queueing.QUEUE}:processing', timeout=2, src='LEFT', dest='RIGHT')
        if item is None:
            continue
        handle_job(item)
        pulse.touch()

if __name__ == '__main__':
    for raw in queueing.broker.lrange(f'{queueing.QUEUE}:processing', 0, -1):
        with queueing.broker.pipeline() as pipe:
            pipe.lpush(queueing.QUEUE, raw)
            pipe.lrem(f'{queueing.QUEUE}:processing', 1, raw)
            pipe.execute()
    serve()
