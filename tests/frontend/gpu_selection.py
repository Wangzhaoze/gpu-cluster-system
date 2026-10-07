"""Render GPU controls and queue badges against a built frontend with synthetic data."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument('--url', required=True)
parser.add_argument('--output', default='/tmp/gpu-selection-ui')
parser.add_argument('--only', choices=['all', 'nav', 'gpus'], default='all')
args = parser.parse_args()
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)
slots = [{'gpu_index': i, 'state': 'FREE', 'external_busy': False, 'metrics': None} for i in range(4)]
queue = [{'id': 'running-debug', 'kind': 'debug', 'status': 'RUNNING', 'requested_gpus': 1, 'requested_gpu_indices': [0], 'username': 'member'}]
requests = []
checks = []
errors = []

def passed(name):
    checks.append(name)
    print('PASS ' + name, flush=True)

def setup(browser, role='MEMBER', maximum=3):
    page = browser.new_page(viewport={'width': 1440, 'height': 1050})
    actor = {'id': 'member', 'username': 'member', 'display_name': 'Member', 'role': role, 'enabled': True, 'max_gpus': maximum, 'max_debug_hours': 10, 'default_environment_id': 'env'}
    def route(route):
        req = route.request
        path = urlsplit(req.url).path.removeprefix('/api')
        result = {}
        if req.method == 'POST':
            requests.append((path, req.post_data_json))
        elif path == '/auth/me': result = actor
        elif path == '/resources/gpus': result = {'mode': 'local-gpu-docker', 'worker_online': True, 'slots': slots, 'telemetry_status': 'online', 'telemetry_sampled_at': '2026-10-07T00:00:00Z', 'telemetry_error': None}
        elif path == '/workspace': result = {'mode': 'container', 'state': 'STOPPED', 'route_path': '/workspace/member/', 'container_id': None, 'environment': {'id': 'env', 'name': 'PyTorch'}, 'venv': '/opt/user-env/venv'}
        elif path == '/resources/queue': result = queue
        elif path == '/environments': result = [{'id': 'env', 'name': 'PyTorch', 'enabled': True, 'available': True}]
        elif path == '/system/remote-access': result = {'status': 'online', 'url': args.url}
        elif path == '/storage': result = {'user_id': 'member', 'username': 'member', 'bytes': {'workspace': 0, 'results': 0, 'scratch': 0}}
        elif path == '/users': result = [actor]
        elif path in ['/jobs', '/debug', '/settings/env', '/admin/storage', '/admin/audit', '/admin/images']: result = []
        route.fulfill(status=200, content_type='application/json', body=json.dumps(result))
    page.route('**/api/**', route)
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(args.url)
    expect(page.locator('nav')).to_be_visible()
    return page

def checkbox(page, index):
    return page.locator('.gpu-choices label').filter(has_text='GPU ' + str(index)).get_by_role('checkbox')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    try:
        if args.only in ['all', 'nav']:
            pages = [setup(browser, role) for role in ['ADMIN', 'MEMBER']]
            for page in pages:
                expect(page.locator('nav button').filter(has_text='训练任务').locator('b')).to_have_count(0)
            queue.extend([{'id': 'pending-train', 'kind': 'train', 'status': 'PENDING', 'requested_gpus': 2, 'requested_gpu_indices': [2, 3], 'username': 'member'}, {'id': 'running-train', 'kind': 'train', 'status': 'RUNNING', 'requested_gpus': 1, 'requested_gpu_indices': [0], 'username': 'member'}])
            for page in pages:
                expect(page.locator('nav button').filter(has_text='训练任务').locator('b')).to_have_text('1', timeout=10000)
            queue[:] = queue[:1]
            for page in pages:
                expect(page.locator('nav button').filter(has_text='训练任务').locator('b')).to_have_count(0, timeout=10000)
                page.close()
            passed('admin/member navigation counts only pending training; running debug/training never creates a badge')
        if args.only in ['all', 'gpus']:
            slots[0]['state'] = 'RUNNING'
            slots[1]['external_busy'] = True
            page = setup(browser)
            for nav, submit, endpoint in [('在线调试', '开启调试', '/debug'), ('训练任务', '提交训练', '/jobs')]:
                page.locator('nav').get_by_role('button', name=nav).click()
                picker = page.locator('.gpu-picker')
                picker.locator('select').select_option('auto')
                expect(picker.locator('input[type=number]')).to_have_attribute('max', '3')
                picker.locator('input[type=number]').fill('4')
                assert not picker.locator('input[type=number]').evaluate('(e) => e.checkValidity()')
                picker.locator('input[type=number]').fill('2')
                picker.locator('select').select_option('manual')
                expect(checkbox(page, 0)).to_be_disabled()
                expect(checkbox(page, 1)).to_be_disabled()
                expect(checkbox(page, 2)).to_be_checked()
                checkbox(page, 3).check()
                expect(picker.locator('input[name=gpu]')).to_have_value('2')
                page.get_by_role('button', name=submit).click()
                expect(page.get_by_text('操作成功', exact=True)).to_have_count(0)
                expect(page.locator('main .alert.success')).to_be_visible()
                request = next(data for path, data in reversed(requests) if path == endpoint)
                assert request['requested_gpus'] == 2 and request['gpu_indices'] == [2, 3], request
                label = page.locator('.gpu-choices label').filter(has_text='GPU 0')
                assert label.evaluate('(e) => getComputedStyle(e).cursor') == 'not-allowed'
                assert label.evaluate('(e) => getComputedStyle(e).backgroundColor') != page.locator('.gpu-choices label').filter(has_text='GPU 2').evaluate('(e) => getComputedStyle(e).backgroundColor')
            passed('debug/training support two selected GPUs and member quota; platform/external busy cards are grey and disabled')
            slots[0]['state'] = 'FREE'
            slots[1]['external_busy'] = False
            expect(checkbox(page, 0)).to_be_enabled(timeout=10000)
            checkbox(page, 0).check()
            expect(checkbox(page, 1)).to_be_disabled()
            slots[3]['external_busy'] = True
            expect(checkbox(page, 3)).not_to_be_checked(timeout=10000)
            expect(checkbox(page, 3)).to_be_disabled()
            expect(page.locator('input[name=gpu]')).to_have_value('2')
            page.screenshot(path=str(out / 'member-multiple-gpus.png'), full_page=True, animations='disabled')
            for slot in slots: slot['state'] = 'RUNNING'
            expect(page.locator('.gpu-choices input:checked')).to_have_count(0, timeout=10000)
            before = len(requests)
            page.get_by_role('button', name='提交训练').click()
            expect(page.get_by_role('alert')).to_contain_text('请至少选择一张显卡')
            assert len(requests) == before
            passed('live occupancy clears selected cards; quota cap and empty manual submissions are enforced')
            for slot in slots: slot['state'] = 'FREE'; slot['external_busy'] = False
            for maximum in [0, 1]:
                limited = setup(browser, maximum=maximum)
                limited.locator('nav').get_by_role('button', name='在线调试').click()
                if maximum == 0:
                    expect(limited.locator('.gpu-picker option[value=manual]')).to_have_attribute('disabled', '')
                    expect(limited.locator('input[name=gpu]')).to_have_value('0')
                else:
                    limited.locator('.gpu-picker select').select_option('manual')
                    expect(checkbox(limited, 0)).to_be_checked()
                    expect(checkbox(limited, 1)).to_be_disabled()
                limited.close()
            passed('members with zero/one GPU quotas retain their own limits')
            page.close()
        assert not errors, errors
    finally:
        browser.close()
(out / 'report.json').write_text(json.dumps({'success': True, 'passed': checks}, indent=2))
print('GPU SELECTION UI PASSED (' + str(len(checks)) + ' checks)', flush=True)
