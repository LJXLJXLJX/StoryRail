"""显式隔离验收；只创建临时项目、容器与 volume，不调用模型。"""

import json
import os
import subprocess
import uuid

import pytest
from test_agent_onboarding import create, login, running

from integrations.agent_launcher.__main__ import AGENT_IMAGE, control

pytestmark = pytest.mark.skipif(
    os.environ.get("STORYRAIL_DOCKER_TESTS") != "1", reason="显式 Docker 验收"
)
IMAGE = AGENT_IMAGE


def docker(*args, input=None, env=None):
    result = subprocess.run(
        ["docker", *args], input=input, capture_output=True, env=env, timeout=60
    )
    assert result.returncode == 0, result.stderr.decode()[-1000:]
    return result.stdout


def test_npm_extension_install_in_read_only_non_root_container():
    # 自建无依赖包验证实际 npm 安装，不下载第三方代码、不使用真实 profile。
    script = r"""
import io,json,os,subprocess,tarfile
from pathlib import Path
package=json.dumps({'name':'storyrail-extension-probe','version':'1.0.0'}).encode()
with tarfile.open('/tmp/probe.tgz','w:gz') as archive:
 info=tarfile.TarInfo('package/package.json'); info.size=len(package)
 archive.addfile(info,io.BytesIO(package))
args=['npm','install','/tmp/probe.tgz','--prefix','/pi/npm','--legacy-peer-deps',
      '--offline','--ignore-scripts','--no-audit','--no-fund']
broken=subprocess.run(args,capture_output=True,env={**os.environ,'npm_config_cache':'/.npm'})
assert broken.returncode!=0 and b'/.npm' in broken.stderr
fixed=subprocess.run(args,capture_output=True)
assert fixed.returncode==0,fixed.stderr.decode()
assert Path('/pi/npm/node_modules/storyrail-extension-probe/package.json').is_file()
assert any(Path('/tmp/npm-cache/_cacache').rglob('*'))
print('npm extension installation passed with writable cache')
"""
    output = docker(
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user",
        "10002:10002",
        "--tmpfs",
        "/tmp:rw,mode=1777",
        "--tmpfs",
        "/pi:rw,uid=10002,gid=10002",
        IMAGE,
        "python",
        "-",
        input=script.encode(),
    )
    assert b"passed" in output


@pytest.mark.parametrize("agent_kind", ["pi", "codex", "agy", "kimi", "dsh", "grok"])
def test_isolated_idle_startup_mcp_read_and_host_denial(agent_kind):
    agent_image = IMAGE
    with running() as (server, local, workspaces):
        pid = create(server, login(server, local))
        config = control(local.socket_path, {"action": "connect", "project_id": pid})
        config["origin"] = "http://gateway:8080"
        prefix = "sr-probe-" + uuid.uuid4().hex[:10]
        network, gateway, agent, volume = prefix, prefix + "-g", prefix + "-a", prefix + "-v"
        env = {
            **os.environ,
            "GATEWAY_TOKEN": "synthetic-unused",
            "PROJECT_ID": pid,
            "CORE_PORT": str(server.server_address[1]),
        }
        docker("network", "create", "--internal", network)
        docker("volume", "create", volume)
        try:
            docker(
                "run",
                "--rm",
                "-i",
                "--network",
                "none",
                "--user",
                "0:0",
                "--mount",
                f"type=volume,source={volume},target=/workspace",
                agent_image,
                "python",
                "-c",
                "import os,sys;from pathlib import Path;p=Path('/workspace/connection.json');"
                "p.write_bytes(sys.stdin.buffer.read());os.chmod(p,0o600);os.chown(p,10002,10002);"
                "os.chown('/workspace',10002,10002)",
                input=json.dumps(config).encode(),
            )
            docker(
                "run",
                "-d",
                "--name",
                gateway,
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--user",
                "10002:10002",
                "--env",
                "GATEWAY_TOKEN",
                "--env",
                "CORE_PORT",
                "--env",
                "PROJECT_ID",
                agent_image,
                "python",
                "/app/gateway.py",
                env=env,
            )
            docker("network", "connect", "--alias", "gateway", network, gateway)
            docker(
                "run",
                "-d",
                "--name",
                agent,
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--user",
                "10002:10002",
                "--network",
                network,
                "--tmpfs",
                "/tmp:rw,mode=1777",
                "--tmpfs",
                "/codex:rw,uid=10002,gid=10002,mode=700",
                "--tmpfs",
                "/agy:rw,uid=10002,gid=10002,mode=700",
                "--tmpfs",
                "/kimi-code:rw,uid=10002,gid=10002,mode=700",
                "--tmpfs",
                "/dsh:rw,uid=10002,gid=10002,mode=700",
                "--tmpfs",
                "/grok:rw,uid=10002,gid=10002,mode=700",
                "--mount",
                f"type=volume,source={volume},target=/workspace",
                agent_image,
                "python",
                "-c",
                "import time;time.sleep(600)",
            )
            script = r"""
import json,socket,urllib.request,urllib.error,subprocess
from pathlib import Path
config=json.loads(Path('/workspace/connection.json').read_text())
# 镜像只允许带 MCP instructions 引用的 Core 纯文本，不包含 Core 源码。
core_files={str(p.relative_to('/app/core')) for p in Path('/app/core').rglob('*') if p.is_file()}
assert core_files <= {'director_proposals/skills/consistency_instruction.md'}
assert not Path('/var/run/docker.sock').exists()
try:
 s=socket.create_connection(('host.docker.internal', CORE_PORT),timeout=2)
except OSError: pass
else: s.close(); raise AssertionError('direct host reachable')
for path in ['/api/local-connection','/api/projects','/api/local-session','/provider']:
 try: urllib.request.urlopen('http://gateway:8080'+path,timeout=5)
 except urllib.error.HTTPError as e: assert e.code==403
 else: raise AssertionError(path)
assert subprocess.run([AGENT_KIND,'--version'],capture_output=True).returncode==0
# 启动入口不得调用 MCP、选择模型或向 Agent 传入初始任务。
import os,runpy,sys
original_exec=os.execvp
def inspect_startup(file,args):
 if AGENT_KIND=='dsh':
  assert file==sys.executable
  assert args==[sys.executable,'/app/client.py','dsh-web']
 elif AGENT_KIND=='pi':
  assert file==AGENT_KIND
  assert args==['pi','--session-dir','/workspace/sessions']
 elif AGENT_KIND=='codex':
  assert file==AGENT_KIND
  assert args[:3]==['codex','--cd','/workspace']
  assert 'mcp_servers.storyrail.required=true' in args
 elif AGENT_KIND=='agy':
  assert file==AGENT_KIND
  assert args==['agy','--dangerously-skip-permissions']
 elif AGENT_KIND=='kimi':
  assert file==AGENT_KIND
  assert args==['kimi','--auto']
 elif AGENT_KIND=='grok':
  assert file==AGENT_KIND
  assert args==['grok']
 raise SystemExit(0)
os.execvp=inspect_startup
sys.argv=['/app/client.py','start',AGENT_KIND]
try:
 runpy.run_path('/app/client.py',run_name='__main__')
except SystemExit as e: assert e.code==0
finally: os.execvp=original_exec
assert json.loads(Path('/workspace/startup.json').read_text())=={
 'project_id':config['project_id'],'revision':config['revision']}
assert not Path('/workspace/core-token').exists()
assert Path('/workspace/AGENTS.md').is_file()
def tool(name,args):
 Path('/workspace/call.json').write_text(json.dumps({'tool':name,'arguments':args}))
 p=subprocess.run(['python','/app/client.py','/workspace/call.json'],capture_output=True)
 assert p.returncode==0,p.stdout.decode()[:1200]+p.stderr.decode()[:1200]
 return json.loads(p.stdout)['structured_content']
r=tool('read_human_handoff',{'project_id':config['project_id'],'expected_revision':config['revision'],'idempotency_key':'handoff'})
assert 'data' in r
if AGENT_KIND=='codex':
 import sys,asyncio
 sys.path.insert(0,'/app')
 from client import codex_command
 native=subprocess.run(codex_command()+['mcp','list','--json'],capture_output=True)
 assert native.returncode==0,native.stderr.decode()
 servers=json.loads(native.stdout)
 assert len(servers)==1 and servers[0]['name']=='storyrail'
 from mcp import Client
 from mcp.client.stdio import StdioServerParameters
 async def native_stdio():
  params=StdioServerParameters(command='python',args=['/app/client.py','mcp'],cwd='/app')
  async with Client(params) as c:
   tools=await c.list_tools()
   assert any(t.name=='read_workflow' for t in tools.tools)
   result=await c.call_tool('read_workflow', {
    'project_id':config['project_id'],'expected_revision':config['revision'],
    'idempotency_key':'native-handoff'})
   assert not result.is_error
 asyncio.run(native_stdio())
if AGENT_KIND=='agy':
 native=subprocess.run(['agy','mcp','list'],capture_output=True)
 assert native.returncode==0,native.stderr.decode()
 assert b'storyrail' in native.stdout
if AGENT_KIND=='kimi':
 import json
 config=json.loads(Path('/kimi-code/mcp.json').read_text())
 assert config == {'mcpServers': {'storyrail': {
  'command': sys.executable, 'args': ['/app/client.py','mcp']}}}
 native=subprocess.run(['kimi','--version'],capture_output=True)
 assert native.returncode==0,native.stderr.decode()
if AGENT_KIND=='dsh':
 os.environ['STORYRAIL_DSH_HOST_PORT']='43210'
 from client import dsh_command
 args=dsh_command()
 assert args[:7]==[
  'node','--expose-internals','/usr/local/lib/node_modules/@deepseek-ai/dsh/lib/bin.js',
  '--profile','web','--port','3080']
 assert args[-1]=='--no-open'
 native=subprocess.run(['dsh','--version'],capture_output=True)
 assert native.returncode==0,native.stderr.decode()
 assert Path('/dsh/cordis.patch.yml').is_file()
 assert os.environ['NARB_DISABLE_NATIVE_CACHE']=='1'
 native=subprocess.run(args+['--help'],capture_output=True,timeout=30)
 assert native.returncode==0,native.stderr.decode()
 assert b'--trusted-host' in native.stdout
if AGENT_KIND=='grok':
 from client import grok_command
 os.environ['GROK_HOME']='/grok'
 assert grok_command()==['grok']
 native=subprocess.run(['grok','--version'],capture_output=True)
 assert native.returncode==0,native.stderr.decode()
 assert Path('/grok/config.toml').is_file()
 assert 'storyrail' in Path('/grok/config.toml').read_text()
print('native agent available; host denied; MCP read-only connection passed')
""".replace("CORE_PORT", str(server.server_address[1])).replace("AGENT_KIND", repr(agent_kind))
            output = docker("exec", "-i", agent, "python", "-", input=script.encode())
            assert b"passed" in output
            assert (
                workspaces.structured_director_store(pid).read().status.value
                == "awaiting_reference_proposal"
            )
        finally:
            for container in (agent, gateway):
                subprocess.run(["docker", "rm", "-f", container], capture_output=True)
            subprocess.run(["docker", "volume", "rm", volume], capture_output=True)
            subprocess.run(["docker", "network", "rm", network], capture_output=True)
