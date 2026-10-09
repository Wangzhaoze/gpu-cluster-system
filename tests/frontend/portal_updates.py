"""Browser regression checks with synthetic APIs; no production accounts/data."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:18081')
parser.add_argument('--output', default='/tmp/gpu-cluster-portal-ui-checks')
args = parser.parse_args()
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)
users = {name: {'id': name, 'username': name, 'display_name': name, 'role': role, 'enabled': True,
              'default_environment_id': 'env', 'max_gpus': 3, 'max_debug_hours': 8}
         for name, role in [('owner', 'MEMBER'), ('other', 'MEMBER'), ('admin', 'ADMIN')]}
slots = [{'gpu_index': i, 'state': 'FREE' if i in [0, 3] else 'RUNNING', 'owner_type': {1: 'debug', 2: 'train'}.get(i),
          'owner_id': None, 'username': 'other' if i in [1, 2] else None, 'started_at': None,
          'external_busy': i == 3, 'metrics': None} for i in range(4)]
base = {'status': 'PENDING', 'requested_gpus': 1, 'requested_cpus': 4, 'requested_ram_mb': 4096,
        'requested_gpu_indices': None, 'assigned_gpus': [], 'time_limit_seconds': 3600,
        'created_at': '2026-10-08T00:00:00Z', 'started_at': None, 'expires_at': None, 'finished_at': None,
        'command': 'python train.py', 'workdir': '/workspace', 'output_name': 'run', 'cancel_requested': False}
records = [{**base, 'id': name + '-train', 'kind': 'train', 'user_id': name, 'username': name} for name in ['owner', 'other']]
announcements = []
reads = set()
mutations, errors, checks = [], [], []
fail_ack = [False]


def passed(name):
    checks.append(name)
    print('PASS ' + name, flush=True)


def routes(actor):
    def route(route):
        request = route.request
        path = urlsplit(request.url).path.removeprefix('/api')
        data = request.post_data_json if request.post_data else None
        result, status = {}, 200
        if request.method in ['POST', 'PATCH', 'DELETE']:
            mutations.append((actor['id'], path, data))
            if path in ['/jobs', '/debug']:
                kind = 'train' if path == '/jobs' else 'debug'
                item = {**base, **data, 'id': 'submitted-' + kind, 'kind': kind, 'username': actor['username'], 'user_id': actor['id'], 'can_manage': True}
                records.append(item)
                result, status = item, 201
            elif path.endswith('/kill'):
                next(item for item in records if item['id'] == path.split('/')[2])['cancel_requested'] = True
            elif path.endswith('/extend'):
                next(item for item in records if item['id'] == path.split('/')[2])['time_limit_seconds'] += data['extra_seconds']
            elif path == '/announcements':
                item = {**data, 'id': 'announcement-' + str(len(announcements)), 'created_at': '2026-10-08T00:00:00Z', 'updated_at': '2026-10-08T00:00:00Z', 'published_at': None}
                announcements.append(item)
                result, status = item, 201
            elif path.startswith('/announcements/'):
                item = next(item for item in announcements if item['id'] == path.split('/')[2])
                if path.endswith('/publish'):
                    item['published_at'] = '2026-10-08T01:00:00Z'
                    result = item
                elif path.endswith('/read'):
                    if fail_ack[0]:
                        fail_ack[0] = False
                        result, status = {'detail': 'Synthetic acknowledgment failure'}, 503
                    else:
                        reads.add((actor['id'], item['id']))
                else:
                    item.update(data)
                    result = item
        elif path == '/auth/me': result = actor
        elif path == '/resources/gpus': result = {'mode': 'local-gpu-docker', 'worker_online': True, 'telemetry_status': 'online', 'telemetry_sampled_at': '2026-10-08T00:00:00Z', 'telemetry_error': None, 'slots': slots}
        elif path == '/workspace': result = {'mode': 'container', 'state': 'STOPPED', 'route_path': '/workspace/owner/', 'container_id': None, 'environment': {'id': 'env', 'name': 'PyTorch'}, 'venv': '/opt/user-env/venv'}
        elif path in ['/jobs', '/debug']:
            kind = 'train' if path == '/jobs' else 'debug'
            result = [{**item, 'can_manage': actor['role'] == 'ADMIN' or item['user_id'] == actor['id']} for item in records if item['kind'] == kind]
        elif path == '/resources/queue': result = [{**item, 'can_manage': actor['role'] == 'ADMIN' or item['user_id'] == actor['id']} for item in records if not item['cancel_requested']]
        elif path == '/environments': result = [{'id': 'env', 'name': 'PyTorch', 'enabled': True, 'available': True}]
        elif path == '/system/remote-access': result = {'status': 'online', 'url': args.url}
        elif path == '/storage': result = {'username': actor['username'], 'bytes': {'workspace': 0, 'results': 0, 'scratch': 0}}
        elif path == '/users': result = list(users.values())
        elif path == '/announcements': result = announcements if actor['role'] == 'ADMIN' else [item for item in announcements if item['published_at'] and (actor['id'], item['id']) not in reads]
        elif path.endswith('/logs'): result = {'log': 'Synthetic training output', 'status': 'PENDING'}
        elif path in ['/settings/env', '/admin/storage', '/admin/audit', '/admin/images']: result = []
        route.fulfill(status=status, content_type='application/json', body=json.dumps(result))
    return route


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    def page_for(name):
        page = browser.new_page(viewport={'width': 1440, 'height': 1050})
        page.route('**/api/**', routes(users[name]))
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(args.url)
        expect(page.locator('nav')).to_be_visible()
        return page
    try:
        member, admin = page_for('owner'), page_for('admin')
        for page in [member, admin]:
            for index, color in enumerate(['rgb(230, 247, 237)', 'rgb(230, 240, 255)', 'rgb(255, 241, 223)', 'rgb(237, 240, 243)']):
                card = page.locator('.gpu-card').nth(index)
                assert card.evaluate('(e) => getComputedStyle(e).backgroundColor') == color
                expect(card.locator('p')).to_contain_text('用户：')
            expect(page.locator('.gpu-card').nth(1).locator('.status')).to_have_text('调试中')
            expect(page.locator('.gpu-card').nth(2).locator('.status')).to_have_text('训练中')
            expect(page.locator('.gpu-card').nth(3).locator('.status')).to_have_text('外部占用')
            assert '显存控制器利用率' not in page.locator('main').inner_text() and '风扇' not in page.locator('main').inner_text()
        member.screenshot(path=str(out / 'member-gpu-overview.png'), full_page=True)
        admin.screenshot(path=str(out / 'admin-gpu-overview.png'), full_page=True)
        passed('GPU card/status colors and user labels match for admin and member; removed metrics stay absent')

        own_queue = member.locator('.queue-list > div').filter(has_text='owner')
        other_queue = member.locator('.queue-list > div').filter(has_text='other')
        expect(own_queue.get_by_role('button', name='Kill', exact=True)).to_be_enabled()
        expect(other_queue.get_by_role('button', name='Kill', exact=True)).to_be_disabled()
        assert other_queue.get_by_role('button', name='Kill', exact=True).evaluate('(e) => getComputedStyle(e).backgroundColor') == 'rgb(241, 243, 245)'
        expect(admin.locator('.queue-list > div').filter(has_text='other').get_by_role('button', name='Kill', exact=True)).to_be_enabled()
        passed('overview training queue exposes own/admin Kill and disabled other-member Kill')

        member.locator('nav').get_by_role('button', name='训练任务').click()
        expect(member.get_by_label('CPU 线程数')).to_have_value('4')
        expect(member.get_by_label('内存 (GB)')).to_have_value('4')
        expect(member.locator('.gpu-picker option[value=cpu]')).to_have_count(0)
        expect(member.locator('input[name=gpu]')).to_have_value('1')
        member.locator('.gpu-picker select').select_option('manual')
        for index in [1, 2, 3]:
            expect(member.locator('.gpu-choices label').filter(has_text='GPU ' + str(index)).get_by_role('checkbox')).to_be_disabled()
        member.locator('.gpu-picker select').select_option('auto')
        member.get_by_role('button', name='提交训练').click()
        expect(member.get_by_role('status')).to_contain_text('任务已提交到队列')
        payload = next(data for user, path, data in mutations if user == 'owner' and path == '/jobs')
        assert payload['requested_cpus'] == 4 and payload['requested_ram_mb'] == 4096 and payload['requested_gpus'] == 1
        own = member.locator('tbody tr').filter(has_text='owner-tr')
        other = member.locator('tbody tr').filter(has_text='other-tr')
        expect(other.get_by_role('button', name='Kill', exact=True)).to_be_disabled()
        expect(member.get_by_role('button', name='延长', exact=True)).to_have_count(0)
        expect(own.get_by_role('link', name='保存 TXT 日志', exact=True)).to_have_attribute('href', '/api/jobs/owner-train/logs/download')
        own.get_by_role('button', name='打开日志', exact=True).click()
        expect(member.get_by_role('dialog', name='任务日志')).to_be_visible()
        expect(member.get_by_role('dialog', name='任务日志').get_by_role('button')).to_have_count(1)
        member.get_by_role('dialog', name='任务日志').get_by_role('button', name='关闭').click()
        passed('4 CPU/4 GB defaults convert to 4096 MiB, GPU is required, occupied GPUs are gray/disabled and TXT link sits beside logs')

        admin.locator('nav').get_by_role('button', name='训练任务').click()
        admin.on('dialog', lambda d: d.accept('2'))
        admin.locator('tbody tr').filter(has_text='other-tr').get_by_role('button', name='延长', exact=True).click()
        expect(admin.get_by_role('status')).to_contain_text('训练时长已延长')
        assert any(path == '/jobs/other-train/extend' and data == {'extra_seconds': 7200} for _, path, data in mutations)
        passed('administrator extension is explicit; members have no extension control')

        member.locator('nav').get_by_role('button', name='在线调试', exact=True).click()
        expect(member.get_by_label('CPU 线程数')).to_have_value('4')
        expect(member.get_by_label('内存 (GB)')).to_have_value('4')
        expect(member.get_by_label('会话时长（小时）')).to_have_attribute('max', '8')
        member.get_by_role('button', name='开启调试').click()
        expect(member.get_by_role('button', name='开启调试')).to_be_disabled()
        expect(member.get_by_text('你已有调试会话，请等待它结束后再创建。')).to_be_visible()
        passed('debug defaults match training, cap is eight hours and an unfinished own session disables a second submission')

        admin.locator('nav').get_by_role('button', name='公告', exact=True).click()
        admin.get_by_label('公告标题').fill('Synthetic notice')
        admin.get_by_label('公告内容').fill('Line one\nLine two <script>plain text</script>')
        admin.get_by_role('button', name='保存草稿', exact=True).click()
        expect(admin.get_by_text('Synthetic notice', exact=True)).to_be_visible()
        expect(member.get_by_role('dialog')).to_have_count(0)
        admin.get_by_role('button', name='预览并发布', exact=True).click()
        expect(admin.get_by_role('dialog')).to_contain_text('Line one')
        expect(member.get_by_role('dialog')).to_have_count(0)
        admin.get_by_role('button', name='确认发布', exact=True).click()
        notice = member.get_by_role('dialog')
        expect(notice).to_contain_text('Synthetic notice', timeout=10000)
        expect(notice).to_contain_text('<script>plain text</script>')
        assert notice.bounding_box()['width'] <= 560
        member.screenshot(path=str(out / 'member-announcement.png'), full_page=True)
        fail_ack[0] = True
        notice.get_by_role('button', name='关闭', exact=True).click()
        expect(notice.get_by_role('alert')).to_contain_text('Synthetic acknowledgment failure')
        notice.get_by_role('button', name='关闭', exact=True).click()
        expect(member.get_by_role('dialog')).to_have_count(0)
        member.reload()
        expect(member.locator('nav')).to_be_visible()
        expect(member.get_by_role('dialog')).to_have_count(0)
        offline = page_for('other')
        expect(offline.get_by_role('dialog')).to_contain_text('Synthetic notice')
        offline.get_by_role('dialog').get_by_role('button', name='关闭', exact=True).click()
        expect(offline.get_by_role('dialog')).to_have_count(0)
        passed('draft preview/confirmation, online and later-login announcement delivery, plain text rendering, retry and durable per-user read state')
        assert not errors, errors
    finally:
        browser.close()
(out / 'report.json').write_text(json.dumps({'success': True, 'checks': checks}, indent=2))
print('PORTAL UPDATE UI PASSED (' + str(len(checks)) + ' checks)', flush=True)
