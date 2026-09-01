"""Execute every algorithm@0.3.0 Runner task in the locked local images.

This is an opt-in 8G acceptance probe. It never pulls images and is intentionally
kept outside CI/release-readiness because it requires the provisioned Docker
Desktop runtime. The reference programs are acceptance fixtures, not learner
submissions and never create capability evidence.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import yaml
from cloud_study_api.runner import DockerRunnerBackend, RuntimeRegistry

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = (
    REPOSITORY_ROOT
    / "skill-packs"
    / "algorithm"
    / "versions"
    / "0.3.0"
    / "assessments"
    / "runner-tasks.yaml"
)
LIMITS = {
    "compile_wall_seconds": 15,
    "run_wall_seconds": 3,
    "compile_memory_mb": 768,
    "run_memory_mb": 256,
    "cpus": 1,
    "compile_pids": 64,
    "run_pids": 32,
    "output_bytes": 65536,
    "tmpfs_mb": 128,
}
EXPECTED_SECURITY = {
    "network": "none",
    "root_filesystem": "read_only",
    "user": "65534:65534",
    "capabilities": "dropped_all",
    "no_new_privileges": True,
    "seccomp": "builtin",
    "host_mounts": "none",
    "docker_socket": "not_mounted",
    "pull_policy": "never",
}

CPP_SOURCES = {
    "p": """#include <iostream>
int main(){long long n; if(!(std::cin>>n)) return 0; std::cout<<n*(n+1)/2<<'\\n';}
""",
    "a": """#include <iostream>
int main(){long long n,i=1,c=0; std::cin>>n; while(i<n){i*=2;++c;} std::cout<<c<<'\\n';}
""",
    "l": """#include <iostream>
#include <vector>
int main(){int n; std::cin>>n; std::vector<long long>a(n); for(auto&x:a)std::cin>>x;
for(int i=n-1;i>=0;--i){if(i<n-1)std::cout<<' ';std::cout<<a[i];}std::cout<<'\\n';}
""",
    "h": """#include <iostream>
#include <set>
int main(){int n;std::cin>>n;std::set<long long>s;while(n--){long long x;std::cin>>x;s.insert(x);}std::cout<<s.size()<<'\\n';}
""",
    "s": """#include <algorithm>
#include <iostream>
#include <vector>
int main(){int n;long long x;std::cin>>n>>x;std::vector<long long>a(n);for(auto&v:a)std::cin>>v;
auto it=std::lower_bound(a.begin(),a.end(),x);std::cout<<(it!=a.end()&&*it==x?it-a.begin():-1)<<'\\n';}
""",
    "r": """#include <iostream>
long long f(int n){return n<2?1:n*f(n-1);}int main(){int n;std::cin>>n;std::cout<<f(n)<<'\\n';}
""",
    "t": """#include <functional>
#include <iostream>
#include <queue>
#include <vector>
int main(){int n;std::cin>>n;std::priority_queue<long long,std::vector<long long>,std::greater<long long>>q;
while(n--){long long x;std::cin>>x;q.push(x);}std::cout<<q.top()<<'\\n';}
""",
    "g": """#include <iostream>
#include <queue>
#include <vector>
int main(){int n,m,s,t;std::cin>>n>>m>>s>>t;std::vector<std::vector<int>>g(n);while(m--){int u,v;std::cin>>u>>v;g[u].push_back(v);g[v].push_back(u);}
std::vector<int>seen(n);std::queue<int>q;q.push(s);seen[s]=1;while(!q.empty()){int u=q.front();q.pop();for(int v:g[u])if(!seen[v]){seen[v]=1;q.push(v);}}std::cout<<seen[t]<<'\\n';}
""",
    "y": """#include <algorithm>
#include <iostream>
#include <limits>
#include <vector>
int main(){int n;std::cin>>n;std::vector<std::pair<long long,long long>>a(n);for(auto&[l,r]:a)std::cin>>l>>r;
std::sort(a.begin(),a.end(),[](auto x,auto y){return x.second<y.second;});long long end=std::numeric_limits<long long>::min();int ans=0;for(auto [l,r]:a)if(l>=end){++ans;end=r;}std::cout<<ans<<'\\n';}
""",
    "d": """#include <iostream>
int main(){int n;std::cin>>n;long long a=0,b=1;while(n--){long long c=a+b;a=b;b=c;}std::cout<<a<<'\\n';}
""",
    "q": """#include <algorithm>
#include <iostream>
#include <vector>
int main(){int n;std::cin>>n;std::vector<long long>a(n);for(auto&x:a)std::cin>>x;auto [lo,hi]=std::minmax_element(a.begin(),a.end());std::cout<<*lo<<' '<<*hi<<'\\n';}
""",
}

PYTHON_SOURCES = {
    "p": "n=int(input()); print(n*(n+1)//2)\n",
    "a": "n=int(input()); i=1; c=0\nwhile i<n: i*=2; c+=1\nprint(c)\n",
    "l": "n=int(input()); a=list(map(int,input().split())) if n else []; print(*a[::-1])\n",
    "h": "n=int(input()); a=list(map(int,input().split())) if n else []; print(len(set(a)))\n",
    "s": "n,x=map(int,input().split()); a=list(map(int,input().split())); print(a.index(x) if x in a else -1)\n",
    "r": "def f(n): return 1 if n<2 else n*f(n-1)\nn=int(input()); print(f(n))\n",
    "t": "import heapq\nn=int(input()); a=list(map(int,input().split())); heapq.heapify(a); print(a[0])\n",
    "g": """from collections import deque
n,m,s,t=map(int,input().split()); g=[[] for _ in range(n)]
for _ in range(m):
 u,v=map(int,input().split()); g[u].append(v); g[v].append(u)
seen={s}; q=deque([s])
while q:
 u=q.popleft()
 for v in g[u]:
  if v not in seen: seen.add(v); q.append(v)
print(1 if t in seen else 0)
""",
    "y": """n=int(input()); a=[tuple(map(int,input().split())) for _ in range(n)]
end=None; ans=0
for left,right in sorted(a,key=lambda item:item[1]):
 if end is None or left>=end: ans+=1; end=right
print(ans)
""",
    "d": "n=int(input()); a,b=0,1\nfor _ in range(n): a,b=b,a+b\nprint(a)\n",
    "q": "n=int(input()); a=list(map(int,input().split())); print(min(a),max(a))\n",
}


def _load_tasks() -> list[dict[str, Any]]:
    payload = yaml.safe_load(TASKS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("skill_version") != "0.3.0":
        raise RuntimeError("algorithm@0.3.0 Runner task document is invalid")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 22:
        raise RuntimeError("8G requires exactly 22 governed Runner tasks")
    return cast(list[dict[str, Any]], tasks)


def _source(task_id: str, language: str) -> str:
    family = task_id.split("-", 1)[0]
    sources = CPP_SOURCES if language == "cpp" else PYTHON_SOURCES
    try:
        return sources[family]
    except KeyError as error:
        raise RuntimeError(f"missing acceptance source for {task_id}") from error


def main() -> int:
    registry = RuntimeRegistry(REPOSITORY_ROOT)
    backend = DockerRunnerBackend(REPOSITORY_ROOT)
    availability = backend.availability()
    if not availability["available"]:
        print(json.dumps({"ok": False, "availability": availability}, indent=2))
        return 1
    stale_before = backend.cleanup_stale()
    results: list[dict[str, Any]] = []
    for task in _load_tasks():
        task_id = cast(str, task["id"])
        language = cast(str, task["language"])
        profile_id = cast(str, task["runtime_profile_id"])
        profile_version = cast(str, task["runtime_profile_version"])
        profile = registry.get(profile_id, profile_version)
        invocation_profile = {
            key: profile[key]
            for key in ("id", "version", "language", "platform", "image")
        }
        source = _source(task_id, language)
        invocation = {
            "protocol_version": "1.1.0",
            "audit_id": str(uuid4()),
            "artifact_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "runtime": invocation_profile,
            "source": {
                "filename": "main.cpp" if language == "cpp" else "main.py",
                "content": source,
            },
            "tests": [
                {
                    "id": test["id"],
                    "stdin": test["stdin"],
                    "expected_stdout": test["expected_stdout"],
                }
                for test in cast(list[dict[str, Any]], task["tests"])
            ],
            "limits": LIMITS,
        }
        result = backend.execute(invocation)
        if result["status"] != "passed" or result["failure_code"] is not None:
            raise RuntimeError(
                f"{task_id} failed:\n{json.dumps(result, ensure_ascii=False, indent=2)}"
            )
        if result["security"] != EXPECTED_SECURITY:
            raise RuntimeError(f"{task_id} returned an unexpected security declaration")
        if result["runtime"]["image"] != profile["image"]:
            raise RuntimeError(f"{task_id} did not use the locked image digest")
        if not result["runtime"]["observed_image_id"]:
            raise RuntimeError(f"{task_id} did not report the observed image ID")
        if any(test_result["status"] != "passed" for test_result in result["tests"]):
            raise RuntimeError(f"{task_id} did not pass every governed test")
        leftovers = backend.cleanup_stale()
        if leftovers:
            raise RuntimeError(f"{task_id} left Runner containers behind: {leftovers}")
        results.append(
            {
                "task_id": task_id,
                "language": language,
                "test_count": len(result["tests"]),
                "image": result["runtime"]["image"],
                "observed_image_id": result["runtime"]["observed_image_id"],
                "status": result["status"],
            }
        )
    final_leftovers = backend.cleanup_stale()
    if final_leftovers:
        raise RuntimeError(
            f"8G validation left Runner containers behind: {final_leftovers}"
        )
    print(
        json.dumps(
            {
                "ok": True,
                "evidence_scope": "infrastructure-and-task-fixture-only",
                "creates_user_capability_evidence": False,
                "availability": availability,
                "stale_removed_before": stale_before,
                "task_count": len(results),
                "test_count": sum(item["test_count"] for item in results),
                "results": results,
                "container_leftovers": final_leftovers,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
