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
systemctl start cloud-study-runner.service

if id -nG cloud-study | tr ' ' '\n' | grep -Fxq docker; then
  echo "FastAPI identity unexpectedly gained Docker access." >&2
  exit 1
fi
if [[ "$(systemctl is-enabled cloud-study-runner.service 2>&1 || true)" != "static" ]]; then
  echo "Remote Runner broker must remain non-enableable before 6D." >&2
  exit 1
fi

docker_version="$(docker version --format '{{.Server.Version}}')"
cpp_id="$(docker image inspect "${cpp_image}" --format '{{.Id}}')"
python_id="$(docker image inspect "${python_image}" --format '{{.Id}}')"
printf '{"ok":true,"docker_server_version":"%s","cpp_image_id":"%s","python_image_id":"%s","broker_enabled":false}\n' \
  "${docker_version}" "${cpp_id}" "${python_id}"
