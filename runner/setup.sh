#!/usr/bin/env bash
# Поднимает self-hosted runner GitHub Actions на этом Mac для workflow «Обновить матрицу».
# Нужен gh (авторизованный под владельцем репозитория) и доступ в интернет. Запуск из корня проекта: bash runner/setup.sh
# Повторный запуск безопасен: перерегистрирует раннер и обновит пути в .env раннера.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${GITHUB_REPO:-$(git -C "$HERE" config --get remote.origin.url | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')}"
DIR="$HOME/actions-runner-matrix"
VER="${RUNNER_VERSION:-$(gh api repos/actions/runner/releases/latest --jq .tag_name | sed 's/^v//')}"
ARCH="$( [ "$(uname -m)" = arm64 ] && echo arm64 || echo x64 )"
PY="$(command -v python3)"

mkdir -p "$DIR" && cd "$DIR"
if [ ! -x ./config.sh ]; then
  echo "скачиваю actions-runner $VER (osx-$ARCH)…"
  curl -sSL -o runner.tar.gz "https://github.com/actions/runner/releases/download/v${VER}/actions-runner-osx-${ARCH}-${VER}.tar.gz"
  tar xzf runner.tar.gz && rm runner.tar.gz
fi
if [ -f .runner ]; then ./svc.sh stop >/dev/null 2>&1 || true; ./svc.sh uninstall >/dev/null 2>&1 || true; fi
TOKEN="$(gh api -X POST "repos/${REPO}/actions/runners/registration-token" --jq .token)"
./config.sh --unattended --url "https://github.com/${REPO}" --token "$TOKEN" --name "matrix-$(hostname -s)" --labels matrix --replace
# окружение раннера (сервис launchd не видит PATH пользователя): проект, python с pandas, docker для ya-tracker
grep -v '^MATRIX_HOME=\|^MATRIX_PYTHON=\|^PATH=' .env > .env.new 2>/dev/null || true
{ cat .env.new; echo "MATRIX_HOME=$HERE"; echo "MATRIX_PYTHON=$PY";
  echo "PATH=$HOME/bin:$(dirname "$PY"):$HOME/.docker/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"; } > .env
rm -f .env.new
./svc.sh install && ./svc.sh start
echo "runner установлен как сервис launchd; проверка: cd $DIR && ./svc.sh status"
