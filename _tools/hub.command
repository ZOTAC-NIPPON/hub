#!/bin/sh
# hub.command -- macOS 用ランチャ。Finder でダブルクリックすると
# ターミナルが開いて対話メニューが出る。
#   正本は _tools/hub.py。ここは「python を探して呼ぶ」だけ。
#
# ダブルクリックで開かない場合は、一度だけ次を実行して実行権限を付ける:
#   chmod +x _tools/hub.command

cd "$(dirname "$0")/.." || exit 2

PY=""
for p in python3 python; do
  if command -v "$p" >/dev/null 2>&1; then
    "$p" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >/dev/null 2>&1 \
      && { PY="$p"; break; }
  fi
done

if [ -z "$PY" ]; then
  echo
  echo "  Python 3.8 以上が見つかりませんでした。"
  echo "  ターミナルで  xcode-select --install  を実行すると入ります。"
  echo
  printf "  Enter で閉じます…"; read -r _
  exit 2
fi

"$PY" "_tools/hub.py" "$@"
RC=$?

# 引数なし（メニュー）のときは、閉じる前に結果が読めるよう止める
if [ $# -eq 0 ]; then
  printf "\n  Enter で閉じます…"; read -r _
fi
exit $RC
