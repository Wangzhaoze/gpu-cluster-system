"""Verify role/data/variable changes using disposable members and workloads."""
import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
import time

import docker
import httpx
from sqlalchemy import select
from app.auth import token_hash
from app.db import SessionLocal
from app.models import AuthSession,User,now

parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);args=parser.parse_args();url=args.url.rstrip('/')
admin=httpx.Client(base_url=url,headers={'Origin':url},timeout=45)
member=httpx.Client(base_url=url,headers={'Origin':url},timeout=45)
other=httpx.Client(base_url=url,headers={'Origin':url},timeout=45)
client=docker.from_env();token=secrets.token_urlsafe(32);users=[];checks=[];success=False;cleanup_errors=[]
key='PORTAL_TEST_'+secrets.token_hex(5).upper();global_added=False
terminal={'COMPLETED','FAILED','CANCELLED','TIMED_OUT','REJECTED'}

def call(session,method,path,body=None,status=200):
 r=session.request(method,'/api'+path,json=body)
 assert r.status_code==status,(method,path,r.status_code,r.text[:200])
 return r.json() if r.content else None

def passed(name):
 checks.append(name);print('PASS '+name,flush=True)

def wait(fn,label,seconds=120):
 until=time.monotonic()+seconds
 while time.monotonic()<until:
  result=fn()
  if result:return result
  time.sleep(1)
 raise AssertionError('Timeout: '+label)

try:
 with SessionLocal() as db:
  actor=db.scalar(select(User).where(User.role=='ADMIN',User.enabled.is_(True)))
  assert actor
  db.add(AuthSession(token_hash=token_hash(token),user_id=actor.id,expires_at=now()+timedelta(minutes=20)));db.commit()
 admin.cookies.set('lab_session',token)
 call(admin,'POST','/jobs',{'command':'true'},403);call(admin,'POST','/debug',{},403);call(admin,'POST','/jobs/missing/retry',None,403)
 assert admin.get('/host/').status_code in (200,302)
 passed('administrator cannot submit/retry workloads and retains native host access')
 image_id=client.images.get(os.environ['LAB_TORCH_IMAGE']).id
 template=next(e for e in call(admin,'GET','/environments') if e['image']==image_id and e['enabled'])
 password=secrets.token_urlsafe(24)
 for _ in range(2):
  users.append(call(admin,'POST','/users',{'username':'portal_'+secrets.token_hex(4),'display_name':'Disposable portal acceptance','password':password,'role':'MEMBER','max_gpus':1,'default_environment_id':template['id']},201))
 owner,outsider=users
 call(member,'POST','/auth/login',{'username':owner['username'],'password':password});call(other,'POST','/auth/login',{'username':outsider['username'],'password':password})
 personal={'user_id':owner['id'],'key':key,'value':'personal'}
 call(admin,'PUT','/settings/env',{'key':key,'value':'global'});global_added=True
 call(member,'PUT','/settings/env',personal)
 call(member,'PUT','/settings/env',{'key':key,'value':'unauthorized'},403)
 call(member,'PUT','/settings/env',{**personal,'user_id':outsider['id']},403)
 call(other,'DELETE','/settings/env/'+key+'?user_id='+owner['id'],None,403)
 assert next(v for v in call(admin,'GET','/settings/env?user_id='+owner['id']) if v['key']==key)['value']=='personal'
 call(member,'PUT','/settings/env',{**personal,'value':'updated-personal'})
 assert next(v for v in call(admin,'GET','/settings/env?user_id='+owner['id']) if v['key']==key)['value']=='updated-personal'
 passed('global/personal variable add/update synchronization and cross-scope rejection')
 stopped=call(member,'GET','/workspace');assert 'host_paths' not in stopped and 'host_import_command' not in stopped
 storage_rows=call(admin,'GET','/admin/storage');path=next(r['workspace_host_path'] for r in storage_rows if r['user_id']==owner['id']);assert path==os.environ['LAB_HOST_ROOT']+'/users/'+owner['username']+'/workspace'
 call(member,'GET','/admin/storage',None,403)
 workspace=call(member,'POST','/workspace/start');container=client.containers.get(workspace['container_id']);mount=next(m for m in container.attrs['Mounts'] if m['Destination']=='/workspace');assert mount['Source']==path
 result=container.exec_run(['python3','-c','import os; assert os.environ['+repr(key)+']=="updated-personal"; print("SCOPED_ENV_OK")']);assert result.exit_code==0,result.output.decode()[-200:]
 passed('host addresses confined to administrator storage; actual workspace receives personal variable')
 call(member,'DELETE','/settings/env/'+key+'?user_id='+owner['id'])
 assert all(v['scope']!=owner['id'] for v in call(admin,'GET','/settings/env?user_id='+owner['id']) if v['key']==key)
 with SessionLocal() as db:
  from app.docker_runtime import runtime
  assert runtime.env(db,db.get(User,owner['id']),{},[],False)[key]=='global'
 call(member,'PUT','/settings/env',personal)
 passed('personal variable deletion and fallback to global; personal value can be restored')
 debug=call(other,'POST','/debug',{'requested_gpus':1,'time_limit_seconds':3600,'approval_reason':'Private disposable reason'},201)
 call(admin,'PATCH','/debug/'+debug['id'],{'time_limit_seconds':7200})
 edited=next(r for r in call(admin,'GET','/debug') if r['id']==debug['id']);assert edited['status'] in {'PENDING','RUNNING'} and edited['time_limit_seconds']==7200
 summary=next(r for r in call(member,'GET','/debug') if r['id']==debug['id']);assert summary['can_manage'] is False and not {'command','route_path','approval_reason','approval_note','container_id','env_keys'} & summary.keys()
 call(member,'GET','/debug/'+debug['id']+'/logs',None,403);call(member,'POST','/debug/'+debug['id']+'/stop',None,403);call(member,'PATCH','/debug/'+debug['id'],{'time_limit_seconds':7200},403)
 passed('public other-member debug summary without private fields; admin duration edit preserves the session')
 job=call(member,'POST','/jobs',{'command':'python -u -c '+__import__('shlex').quote('import os,time; print("TASK_ENV="+os.environ['+repr(key)+']); time.sleep(120)'),'requested_gpus':1,'requested_ram_mb':1024,'time_limit_seconds':180,'env':{key:'task-override'}},201)
 wait(lambda:'TASK_ENV=task-override' in call(member,'GET','/jobs/'+job['id']+'/logs')['log'],'GPU-required training variable injection')
 prior=call(admin,'GET','/jobs/'+job['id'])
 call(admin,'PATCH','/jobs/'+job['id'],{'time_limit_seconds':240})
 updated=call(admin,'GET','/jobs/'+job['id']);assert updated['time_limit_seconds']==240 and updated['container_id']==prior['container_id']
 snapshot=next(r for r in call(other,'GET','/jobs') if r['id']==job['id']);assert not snapshot['can_manage'] and 'command' not in snapshot and 'error_message' not in snapshot
 call(other,'GET','/jobs/'+job['id'],None,403);call(other,'GET','/jobs/'+job['id']+'/logs',None,403);call(other,'POST','/jobs/'+job['id']+'/cancel',None,403)
 passed('member GPU training runs with task variable priority; running duration edit preserves container and private logs')
 busy=next((s for s in call(admin,'GET','/resources/gpus')['slots'] if s['state']!='FREE'),None)
 if busy:
  queued=call(member,'POST','/jobs',{'command':'python -c "print(1)"','requested_gpus':1,'gpu_indices':[busy['gpu_index']],'requested_ram_mb':1024,'time_limit_seconds':60},201)
  update=call(admin,'PATCH','/jobs/'+queued['id'],{'command':'python -c "print(2)"','requested_cpus':2,'requested_ram_mb':2048,'time_limit_seconds':120})
  assert update['status']=='PENDING' and update['command']=='python -c "print(2)"'
  assert any(r['id']==queued['id'] for r in call(other,'GET','/resources/queue'))
  passed('queued training command/resource editing and shared selected-GPU queue')
 success=True
finally:
 for account in users:
  try:
   for endpoint,action in [('jobs','cancel'),('debug','stop')]:
    for record in call(admin,'GET','/'+endpoint):
     if record['user_id']==account['id'] and record['status'] not in terminal:
      call(admin,'POST','/'+endpoint+'/'+record['id']+'/'+action)
   wait(lambda:all(r['status'] in terminal for ep in ['jobs','debug'] for r in call(admin,'GET','/'+ep) if r['user_id']==account['id']),'test workload cleanup')
   call(admin,'POST','/workspace/stop?user_id='+account['id']);call(admin,'POST','/users/'+account['id']+'/disable');call(admin,'DELETE','/users/'+account['id'])
  except Exception as error:cleanup_errors.append(str(error))
 if global_added:
  try:call(admin,'DELETE','/settings/env/'+key)
  except Exception as error:cleanup_errors.append(str(error))
 with SessionLocal() as db:
  session=db.get(AuthSession,token_hash(token))
  if session:db.delete(session);db.commit()
 for session in [admin,member,other]:session.close()
 Path('/runtime/logs/acceptance-role-portals.json').write_text(json.dumps({'success':success and not cleanup_errors,'url':url,'passed':checks,'cleanup_errors':cleanup_errors},indent=2))
 if cleanup_errors:raise AssertionError('Cleanup failed: '+str(cleanup_errors))
print('ROLE PORTAL ACCEPTANCE PASSED ('+str(len(checks))+' checks)',flush=True)
