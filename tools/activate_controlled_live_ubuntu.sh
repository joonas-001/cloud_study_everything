#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --apply --expected-app-commit <40-hex> --expected-runner-commit <40-hex>" >&2
  exit 2
}

if [[ "${1:-}" != "--apply" ]]; then
  usage
fi
shift

expected_app_commit=""
expected_runner_commit=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --expected-app-commit)
      [[ $# -ge 2 ]] || usage
      expected_app_commit="$2"
      shift 2
      ;;
    --expected-runner-commit)
      [[ $# -ge 2 ]] || usage
      expected_runner_commit="$2"
      shift 2
      ;;
    *) usage ;;
  esac
done

if [[ ! "${expected_app_commit}" =~ ^[0-9a-f]{40}$ ]] \
  || [[ ! "${expected_runner_commit}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Both expected commits must be exact lowercase 40-character Git hashes." >&2
  exit 2
fi
if [[ "$(id -u)" -ne 0 ]]; then
  echo "Controlled activation must run as root." >&2
  exit 2
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
  echo "Controlled activation is locked to Ubuntu 24.04." >&2
  exit 1
fi

app_root=/opt/cloud-study/app
runner_root=/opt/cloud-study/runner/current
environment_file=/etc/cloud-study/private-preview.env
policy_path="${app_root}/deployment/policies/single-user-singapore-v2.json"
runner_socket=/run/cloud-study-runner/runner.sock
app_marker="${app_root}/.cloud-study-commit"
runner_marker="${runner_root}/.cloud-study-commit"
rollback_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
environment_backup="${environment_file}.pre-6d-${rollback_stamp}"
activation_complete=false
matrix_file=""

rollback() {
  local exit_code=$?
  if [[ "${activation_complete}" != "true" ]]; then
    systemctl stop cloud-study-api.service >/dev/null 2>&1 || true
    systemctl disable --now cloud-study-runner.service >/dev/null 2>&1 || true
    if [[ -f "${environment_backup}" ]]; then
      install --owner root --group root --mode 0600 \
        "${environment_backup}" "${environment_file}"
    fi
    if [[ -n "${matrix_file}" && "${matrix_file}" == /run/cloud-study-runner/* ]]; then
      rm -f "${matrix_file}"
    fi
    systemctl restart cloud-study-api.service >/dev/null 2>&1 || true
  fi
  exit "${exit_code}"
}

if [[ "$(tr -d '\r\n' < "${app_marker}")" != "${expected_app_commit}" ]]; then
  echo "The live app commit marker does not match the authorized exact commit." >&2
  exit 1
fi
if [[ "$(tr -d '\r\n' < "${runner_marker}")" != "${expected_runner_commit}" ]]; then
  echo "The Runner commit marker does not match the authorized exact commit." >&2
  exit 1
fi
if [[ "$(readlink -f "${runner_root}")" != "/opt/cloud-study/runner/releases/${expected_runner_commit:0:7}" ]]; then
  echo "The Runner current symlink does not target the expected immutable release." >&2
  exit 1
fi
if [[ ! -f "${environment_file}" || "$(stat -c '%a:%U:%G' "${environment_file}")" != "600:root:root" ]]; then
  echo "The private deployment environment must be a root-owned 0600 file." >&2
  exit 1
fi
if ! systemctl is-active --quiet cloud-study-api.service; then
  echo "The existing API must be healthy before controlled activation." >&2
  exit 1
fi
if ! cmp -s \
  "${runner_root}/deployment/systemd/cloud-study-runner.service" \
  /etc/systemd/system/cloud-study-runner.service; then
  echo "The installed Runner unit does not match the exact Runner release." >&2
  exit 1
fi
for service in api web backup; do
  if ! cmp -s \
    "${app_root}/deployment/systemd/cloud-study-${service}.service" \
    "/etc/systemd/system/cloud-study-${service}.service"; then
    echo "The installed ${service} unit does not match the exact app release." >&2
    exit 1
  fi
done
if id -nG cloud-study | tr ' ' '\n' | grep -Fxq docker; then
  echo "FastAPI identity must not have Docker access." >&2
  exit 1
fi
if ! id -nG cloud-study-runner | tr ' ' '\n' | grep -Fxq docker; then
  echo "The dedicated Runner broker identity is missing Docker access." >&2
  exit 1
fi

python3 - "${policy_path}" <<'PY'
import json
import sys
from pathlib import Path

policy = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if policy.get("version") != "1.1.0":
    raise SystemExit("The 6D deployment policy must be version 1.1.0.")
if policy.get("runner", {}).get("remote_enabled") is not True:
    raise SystemExit("The 6D deployment policy must explicitly enable the remote Runner.")
external = policy.get("external_calls", {})
if external != {
    "enabled_by_default": False,
    "real_ai": False,
    "real_sources": False,
    "email": False,
}:
    raise SystemExit("External AI, sources, and email must remain disabled in 6D.")
PY

cpp_image='gcc@sha256:c101370f78e4a30be178c11dd18aeee64c65d617908a98157db2392ca73ab04f'
python_image='python@sha256:843ef86c4efef6d065c1767855730cc974e4998e66d65d6739449f0bc0ae4d93'
docker image inspect "${cpp_image}" "${python_image}" >/dev/null
if [[ "$(docker version --format '{{.Server.Version}}')" != "29.1.3" ]]; then
  echo "Docker Engine drifted from the cloud-validated 29.1.3 baseline." >&2
  exit 1
fi
if [[ -n "$(docker ps -aq --filter label=cloud-study.runner=1.1.0)" ]]; then
  echo "Managed Runner containers must be absent before activation." >&2
  exit 1
fi

install --owner root --group root --mode 0600 \
  "${environment_file}" "${environment_backup}"
trap rollback EXIT
python3 - "${environment_file}" "${policy_path}" "${runner_socket}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
updates = {
    "CLOUD_STUDY_DEPLOYMENT_POLICY_PATH": sys.argv[2],
    "CLOUD_STUDY_RUNNER_SOCKET": sys.argv[3],
}
output = []
seen = set()
for raw_line in path.read_text(encoding="utf-8").splitlines():
    key = raw_line.split("=", 1)[0] if "=" in raw_line else ""
    if key in updates:
        if key not in seen:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        continue
    output.append(raw_line)
for key, value in updates.items():
    if key not in seen:
        output.append(f"{key}={value}")
path.write_text("\n".join(output) + "\n", encoding="utf-8")
PY
chmod 0600 "${environment_file}"
chown root:root "${environment_file}"

systemctl daemon-reload
systemctl enable --now cloud-study-runner.service
for _attempt in {1..40}; do
  if systemctl is-active --quiet cloud-study-runner.service \
    && [[ -S "${runner_socket}" ]]; then
    break
  fi
  sleep 0.25
done
if ! systemctl is-active --quiet cloud-study-runner.service \
  || [[ ! -S "${runner_socket}" ]]; then
  echo "Runner broker did not become ready." >&2
  exit 1
fi

matrix_file="$(mktemp /run/cloud-study-runner/matrix.XXXXXX)"
runuser -u cloud-study -- \
  "${runner_root}/apps/api/.venv/bin/python" \
  "${runner_root}/tools/verify_runner_live.py" \
  --socket "${runner_socket}" >"${matrix_file}"
python3 - "${matrix_file}" <<'PY'
import json
import sys
from pathlib import Path

result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if result.get("ok") is not True or result.get("transport") != "unix_broker":
    raise SystemExit("The governed Runner matrix did not pass through the Unix broker.")
if len(result.get("cases", [])) != 10:
    raise SystemExit("The governed Runner matrix did not report all ten cases.")
PY
rm -f "${matrix_file}"
matrix_file=""
if [[ -n "$(docker ps -aq --filter label=cloud-study.runner=1.1.0)" ]]; then
  echo "Runner containers remained after the activation matrix." >&2
  exit 1
fi

systemctl restart cloud-study-api.service
for _attempt in {1..40}; do
  if curl --fail --silent --show-error http://127.0.0.1:8000/health >/dev/null; then
    break
  fi
  sleep 0.25
done
if ! systemctl is-active --quiet cloud-study-api.service \
  || ! systemctl is-enabled --quiet cloud-study-runner.service; then
  echo "API or persistent Runner service did not reach the required state." >&2
  exit 1
fi

owner_login="$(grep -m1 '^CLOUD_STUDY_OWNER_LOGIN=' "${environment_file}" | cut -d= -f2-)"
if [[ -z "${owner_login}" ]]; then
  echo "The exact owner login is missing after activation." >&2
  exit 1
fi
matrix_file="$(mktemp /run/cloud-study-runner/status.XXXXXX)"
curl --fail --silent --show-error \
  --header "Tailscale-User-Login: ${owner_login}" \
  http://127.0.0.1:8000/deployment/status >"${matrix_file}"
python3 - "${matrix_file}" <<'PY'
import json
import sys
from pathlib import Path

status = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if status.get("remote_runner_enabled") is not True:
    raise SystemExit("The live API did not load the 6D Runner-enabled policy.")
if status.get("external_calls_enabled") is not False:
    raise SystemExit("The live API unexpectedly enabled external calls.")
PY
curl --fail --silent --show-error \
  --header "Tailscale-User-Login: ${owner_login}" \
  http://127.0.0.1:8000/runner/availability >"${matrix_file}"
python3 - "${matrix_file}" <<'PY'
import json
import sys
from pathlib import Path

availability = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if availability.get("available") is not True:
    raise SystemExit("The live API cannot reach the activated Runner broker.")
PY
rm -f "${matrix_file}"
matrix_file=""

activation_complete=true
trap - EXIT
printf '{"ok":true,"app_commit":"%s","runner_commit":"%s","runner_enabled":true,"environment_backup":"%s"}\n' \
  "${expected_app_commit}" "${expected_runner_commit}" "${environment_backup}"
