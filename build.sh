#!/usr/bin/env bash
# Сборка курса в один автономный HTML-файл: dist/claude-s-nulya.html
# Запуск: bash build.sh
set -e
cd "$(dirname "$0")"
mkdir -p dist
{
  echo '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
  echo '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
  cat src/head.html            # стили и <title>
  echo '</head><body>'
  cat src/body.html            # каркас страницы
  echo '<script>'
  cat src/data1.js src/data2.js src/app.js   # контент, данные автора, логика
  echo '</script></body></html>'
} > dist/claude-s-nulya.html
echo "Готово: dist/claude-s-nulya.html ($(wc -c < dist/claude-s-nulya.html) байт)"
