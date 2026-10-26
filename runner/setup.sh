#!/usr/bin/env bash
# Поднимает self-hosted runner GitHub Actions на этом Mac для workflow «Обновить матрицу».
# Нужен gh (авторизованный) и доступ в интернет. Запускать из корня проекта: bash runner/setup.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${GITHUB_REPO:-$(git -C "$HERE" config --get remote.origin.url | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')}"
DIR="$HOME/actions-runner-matrix"
VER="${RUNNER_VERSION:-2.329.0}"
ARCH="$( [ "$(uname -m)" = arm64 ] && echo arm64 || echo x64 )"

mkdir -p "$DIR" && cd "$DIR"
if [ ! -x ./config.sh ]; then
  echo "скачиваю actions-runner $VER (osx-$ARCH)…"
  curl -sSL -o runner.tar.gz "https://github.com/actions/runner/releases/download/v${VER}/actions-runner-osx-${ARCH}-${VER}.tar.gz"
  tar xzf runner.tar.gz && rm runner.tar.gz
fi
TOKEN="$(gh api -X POST "repos/${REPO}/actions/runners/registration-token" --jq .token)"
./config.sh --unattended --url "https://github.com/${REPO}" --token "$TOKEN" --name "matrix-$(hostname -s)" --labels matrix --replace
printf 'MATRIX_HOME=%s\n' "$HERE" >> .env     # путь к проекту с data/ и .env — читает workflow
./svc.sh install && ./svc.sh start
echo "runner установлен как сервис launchd; проверка: ./svc.sh status (в $DIR)"
