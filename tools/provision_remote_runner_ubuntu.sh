#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--apply" ]]; then
  echo "Refusing to change the host without --apply." >&2
  exit 2
fi
if [[ "$(id -u)" -ne 0 ]]; then
  echo "Remote Runner provisioning must run as root." >&2
  exit 2
fi
if [[ ! -f /etc/os-release ]]; then
  echo "Ubuntu release metadata is unavailable." >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
  echo "Remote Runner provisioning is locked to Ubuntu 24.04." >&2
  exit 1
fi
expected_release="$(readlink -f /opt/cloud-study/runner/current)"
if [[ -z "${expected_release}" || "$(pwd -P)" != "${expected_release}" ]]; then
  echo "Run this script from the isolated /opt/cloud-study/runner/current release." >&2
  exit 1
fi
if ! id cloud-study >/dev/null 2>&1; then
  echo "The existing cloud-study service identity is missing." >&2
  exit 1
fi
if id -nG cloud-study | tr ' ' '\n' | grep -Fxq docker; then
  echo "FastAPI identity must never belong to the docker group." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install --yes --no-install-recommends docker.io
systemctl enable --now docker.service

if ! getent group docker >/dev/null; then
  echo "Docker group was not created." >&2
  exit 1
fi
if ! id cloud-study-runner >/dev/null 2>&1; then
  useradd \
    --system \
    --no-create-home \
    --shell /usr/sbin/nologin \
    --gid cloud-study \
    --groups docker \
    cloud-study-runner
fi
if ! id -nG cloud-study-runner | tr ' ' '\n' | grep -Fxq docker; then
  usermod --append --groups docker cloud-study-runner
fi

broker_python="${expected_release}/apps/api/.venv/bin/python"
if ! runuser -u cloud-study-runner -- test -x "${broker_python}"; then
  echo "Runner candidate Python must be executable by cloud-study-runner; do not link the virtual environment into /root." >&2
  exit 1
fi
python_version="$(
  runuser -u cloud-study-runner -- \
    "${broker_python}" -c 'import platform; print(platform.python_version())'
)"
if [[ "${python_version}" != "3.14.3" ]]; then
  echo "Runner candidate Python must remain locked to 3.14.3; observed ${python_version}." >&2
  exit 1
fi
if ! runuser -u cloud-study-runner -- \
  "${broker_python}" -c 'from cloud_study_api.runner_broker import serve_runner_broker'; then
  echo "Runner candidate dependencies are not importable by cloud-study-runner." >&2
  exit 1
fi

cpp_image='gcc@sha256:c101370f78e4a30be178c11dd18aeee64c65d617908a98157db2392ca73ab04f'
python_image='python@sha256:843ef86c4efef6d065c1767855730cc974e4998e66d65d6739449f0bc0ae4d93'
docker pull --platform linux/amd64 "${cpp_image}"
docker pull --platform linux/amd64 "${python_image}"
docker image inspect "${cpp_image}" "${python_image}" >/dev/null

install \
  --owner root \
  --group root \
  --mode 0644 \
  deployment/systemd/cloud-study-runner.service \
  /etc/systemd/system/cloud-study-runner.service
systemctl daemon-reload
systemctl disable cloud-study-runner.service >/dev/null 2>&1 || true
systemctl start cloud-study-runner.service

broker_ready=false
for _attempt in {1..20}; do
  if systemctl is-active --quiet cloud-study-runner.service \
    && [[ -S /run/cloud-study-runner/runner.sock ]]; then
    broker_ready=true
    break
  fi
  sleep 0.25
done
if [[ "${broker_ready}" != "true" ]]; then
  systemctl stop cloud-study-runner.service
  echo "Remote Runner broker did not become active with a ready Unix socket." >&2
  exit 1
fi

if id -nG cloud-study | tr ' ' '\n' | grep -Fxq docker; then
  echo "FastAPI identity unexpectedly gained Docker access." >&2
  exit 1
fi
if [[ "$(systemctl is-enabled cloud-study-runner.service 2>&1 || true)" != "disabled" ]]; then
  echo "Remote Runner broker must remain disabled until controlled activation." >&2
  exit 1
fi

docker_version="$(docker version --format '{{.Server.Version}}')"
cpp_id="$(docker image inspect "${cpp_image}" --format '{{.Id}}')"
python_id="$(docker image inspect "${python_image}" --format '{{.Id}}')"
printf '{"ok":true,"docker_server_version":"%s","cpp_image_id":"%s","python_image_id":"%s","broker_enabled":false}\n' \
  "${docker_version}" "${cpp_id}" "${python_id}"
