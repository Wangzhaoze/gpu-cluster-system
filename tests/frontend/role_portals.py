"""Render the production frontend with synthetic role data; never use real credentials."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import sync_playwright, expect

parser=argparse.ArgumentParser()
parser.add_argument('--url',default='http://127.0.0.1:18080')
parser.add_argument('--output',default='/tmp/role-portal-ui')
args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
users=[{'id':name,'username':name,'display_name':name,'role':role,'enabled':True,'default_environment_id':'env','max_gpus':1,'max_debug_hours':8} for name,role in [('owner','MEMBER'),('other','MEMBER'),('admin','ADMIN')]]
variables=[{'scope':'global','key':'SHARED_MODEL','value':'global-value'},{'scope':'owner','key':'PERSONAL_MODEL','value':'personal-value'}]
base={'kind':'train','status':'PENDING','command':'python private_train.py','workdir':'/workspace','output_name':'run','requested_cpus':1,'requested_ram_mb':4096,'requested_gpus':1,'requested_gpu_indices':[0],'assigned_gpus':[],'time_limit_seconds':3600,'approval_status':'NOT_REQUIRED','approval_reason':'','approval_note':'','created_at':'2026-10-06T18:00:00Z','started_at':None,'finished_at':None,'expires_at':None,'route_path':'/debug/private/','exit_code':None,'error_message':None,'cancel_requested':False,'can_manage':True}
records=[dict(base,id=name+'-'+kind,user_id=name,username=name,kind=kind) for name in ['owner','other'] for kind in ['train','debug']]
mutations=[];checks=[];errors=[]

def passed(name):
 checks.append(name);print('PASS '+name,flush=True)

def route_api(actor):
 def route(route):
  req=route.request;url=urlsplit(req.url);path=url.path.removeprefix('/api');query=parse_qs(url.query);data=req.post_data_json if req.post_data else None
  result={};status=200
  if req.method in ['PUT','POST','PATCH','DELETE']:
   mutations.append((actor['role'],req.method,path,data))
   if path=='/settings/env' and req.method=='PUT':
    scope=data.get('user_id') or 'global';variables[:]=[v for v in variables if not(v['scope']==scope and v['key']==data['key'])];variables.append({'scope':scope,'key':data['key'],'value':data['value']})
   elif path.startswith('/settings/env/') and req.method=='DELETE':
    scope=query.get('user_id',['global'])[0];variables[:]=[v for v in variables if not(v['scope']==scope and v['key']==path.split('/')[-1])]
   elif req.method=='PATCH' and path.startswith(('/jobs/','/debug/')):
    record=next(r for r in records if r['id']==path.split('/')[-1]);record.update(data);result=record
  elif path=='/auth/me': result=actor
  elif path=='/resources/gpus': result={'mode':'local-gpu-docker','worker_online':True,'telemetry_status':'online','telemetry_sampled_at':'2026-10-06T18:00:00Z','telemetry_error':None,'slots':[{'gpu_index':i,'state':'FREE','owner_id':None,'owner_type':None,'username':None,'started_at':None,'external_busy':False,'metrics':None} for i in range(4)]}
  elif path=='/workspace':
   result={'mode':'host','state':'RUNNING','route_path':'/host/','container_id':None,'host_user':'local','host_home':'/home/local','host_uid':1000,'host_gid':1000,'host_python':'/home/local/miniconda3/envs/dl/bin/python','error_message':''} if actor['role']=='ADMIN' else {'mode':'container','state':'STOPPED','route_path':'/workspace/owner/','container_id':None,'environment':{'id':'env','name':'PyTorch','image':'test','image_version':'2.7.1'},'venv':'/opt/user-env/venv'}
  elif path in ['/jobs','/debug']:
   kind='train' if path=='/jobs' else 'debug';result=[]
   for record in records:
    if record['kind']!=kind: continue
    if actor['role']=='ADMIN' or record['user_id']==actor['id']: result.append(record)
    else:
     summary={k:record[k] for k in ['id','kind','user_id','username','status','requested_gpus','requested_gpu_indices','assigned_gpus','time_limit_seconds','created_at','started_at','expires_at','finished_at']};summary['can_manage']=False;result.append(summary)
  elif path=='/resources/queue': result=[{**{k:r[k] for k in ['id','kind','status','requested_gpus','requested_gpu_indices','username','cancel_requested']},'can_manage':actor['role']=='ADMIN' or r['user_id']==actor['id']} for r in records]
  elif path=='/environments': result=[{'id':'env','name':'PyTorch','image':'test','image_version':'2.7.1','description':'','enabled':True,'available':True,'recommended':True}]
  elif path=='/users': result=users
  elif path in ['/admin/storage','/storage']:
   result=[{'username':u['username'],'user_id':u['id'],'role':u['role'],'workspace_host_path':'/host/runtime/users/'+u['username']+'/workspace' if u['role']=='MEMBER' else None,'bytes':{'workspace':1024,'results':0,'scratch':0}} for u in users] if path=='/admin/storage' else {'username':actor['username'],'bytes':{'workspace':1024,'results':0,'scratch':0}}
  elif path in ['/admin/audit','/admin/images','/announcements']: result=[]
  elif path=='/system/remote-access': result={'status':'online','url':'https://example.trycloudflare.com'}
  elif path=='/settings/env':
   scopes=[query.get('user_id',['global'])[0]] if actor['role']=='ADMIN' else ['global',actor['id']];result=[v for v in variables if v['scope'] in scopes]
  route.fulfill(status=status,content_type='application/json',body=json.dumps(result))
 return route

with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 try:
  admin=browser.new_page(viewport={'width':1440,'height':1050});admin.route('**/api/**',route_api(users[2]));admin.on('pageerror',lambda e:errors.append(str(e)));admin.goto(args.url);expect(admin.locator('nav')).to_be_visible()
  assert admin.locator('nav button').last.inner_text()=='帮助'
  expect(admin.get_by_role('button',name='＋ 新建训练')).to_have_count(0)
  admin_color=admin.locator('aside').evaluate('(e)=>getComputedStyle(e).backgroundColor')
  admin.locator('nav').get_by_role('button',name='训练任务').click();expect(admin.get_by_text('新建训练任务',exact=True)).to_have_count(0);expect(admin.get_by_role('button',name='编辑',exact=True)).to_have_count(2)
  admin.get_by_role('button',name='编辑',exact=True).first.click();expect(admin.get_by_role('dialog')).to_be_visible();admin.locator('input[name=time]').fill('7200');admin.get_by_role('button',name='保存修改').click();expect(admin.get_by_role('dialog')).to_have_count(0)
  assert any(m[1]=='PATCH' and m[3]['time_limit_seconds']==7200 for m in mutations)
  admin.get_by_role('button',name='在线调试',exact=True).click();expect(admin.get_by_text('新建调试会话',exact=True)).to_have_count(0)
  passed('admin management-only dashboard, training/debug pages and working edit dialog')
  admin.get_by_role('button',name='宿主机',exact=True).click();expect(admin.locator('main a')).to_have_count(1);expect(admin.get_by_role('link',name='远程 vscode')).to_be_visible();expect(admin.get_by_text('打开集群项目',exact=True)).to_have_count(0);expect(admin.locator('main pre')).to_have_count(0)
  admin.screenshot(path=str(out/'admin-host.png'),full_page=True,animations="disabled")
  admin.get_by_role('button',name='存储',exact=True).click();expect(admin.get_by_role('columnheader',name='workspace 宿主机地址')).to_be_visible();expect(admin.locator('.host-path')).to_have_count(2)
  passed('minimal native host panel and member host addresses in administrator storage')
  member=browser.new_page(viewport={'width':1440,'height':1050});member.route('**/api/**',route_api(users[0]));member.on('pageerror',lambda e:errors.append(str(e)));member.on('dialog',lambda dialog:dialog.accept());member.goto(args.url);expect(member.locator('nav')).to_be_visible()
  member_color=member.locator('aside').evaluate('(e)=>getComputedStyle(e).backgroundColor');assert admin_color!=member_color and member_color=='rgb(20, 57, 47)'
  member.get_by_role('button',name='工作区',exact=True).click();expect(member.locator('main .panel')).to_have_count(1);expect(member.get_by_text('需要 GPU 时使用在线调试或训练任务')).to_be_visible();assert 'host-path' not in member.locator('main').inner_html();member.screenshot(path=str(out/'member-workspace.png'),full_page=True,animations="disabled")
  passed('blue admin versus unchanged green member theme; minimal member workspace')
  member.locator('nav').get_by_role('button',name='训练任务').click();expect(member.get_by_text('新建训练任务',exact=True)).to_be_visible();other=member.locator('tbody tr').filter(has_text='other');expect(other.get_by_role('button',name='Kill',exact=True)).to_be_disabled();expect(other.locator('.log-unavailable')).to_be_visible();assert 'private_train' not in other.inner_text()
  member.get_by_role('button',name='在线调试',exact=True).click();expect(member.get_by_text('新建调试会话',exact=True)).to_be_visible();other=member.locator('.debug-row').filter(has_text='other');expect(other.get_by_role('button')).to_have_count(0);expect(other.get_by_role('link')).to_have_count(0)
  passed('member submission forms and other-member summaries without editor/log/control actions')
  admin.get_by_role('button',name='环境',exact=True).click();admin.get_by_label('变量作用范围').select_option('owner')
  member.get_by_role('button',name='环境',exact=True).click();panel=member.locator('section').filter(has=member.get_by_role('heading',name='环境变量',exact=True));global_row=panel.locator('tr').filter(has_text='SHARED_MODEL');expect(global_row.get_by_role('button')).to_have_count(0)
  panel.locator('input[name=key]').fill('UI_TEST');panel.locator('input[name=value]').fill('new-value');panel.get_by_role('button',name='新增变量').click();expect(panel.locator('tr').filter(has_text='UI_TEST')).to_be_visible()
  row=panel.locator('tr').filter(has_text='UI_TEST');row.get_by_role('button',name='编辑').click();panel.locator('input[name=value]').fill('updated-value');panel.get_by_role('button',name='更新变量').click();expect(row.get_by_text('updated-value',exact=True)).to_be_visible()
  expect(admin.locator('tr').filter(has_text='UI_TEST').get_by_text('updated-value',exact=True)).to_be_visible(timeout=10000)
  row.get_by_role('button',name='删除').click();expect(panel.locator('tr').filter(has_text='UI_TEST')).to_have_count(0)
  assert all(set(m[3])=={'user_id','key','value'} for m in mutations if m[1]=='PUT')
  passed('member variable add/edit/delete and administrator polling synchronization; no unused flags')
  for page in [admin,member]:
   page.get_by_role('button',name='远程访问',exact=True).click();expect(page.locator('main .panel')).to_have_count(1);expect(page.locator('main ol')).to_have_count(0)
   page.get_by_role('button',name='帮助',exact=True).click();expect(page.get_by_role('img',name='GPU Lab 系统架构')).to_be_visible();expect(page.get_by_role('heading',name='1. 登录与远程访问')).to_be_visible()
  admin.screenshot(path=str(out/'admin-help.png'),full_page=True,animations="disabled")
  member.set_viewport_size({'width':390,'height':844});member.screenshot(path=str(out/'member-help-mobile.png'),full_page=True,animations="disabled")
  assert not errors,errors
  passed('one-panel remote access and last-menu Help with architecture, desktop/mobile rendering and no React errors')
 finally:
  if len(checks)<6:
   admin.screenshot(path=str(out/'failure.png'),full_page=True,animations="disabled")
  browser.close()
(out/'report.json').write_text(json.dumps({'success':True,'passed':checks,'admin_sidebar':admin_color,'member_sidebar':member_color},indent=2))
print('ROLE UI ACCEPTANCE PASSED ('+str(len(checks))+' checks)',flush=True)
