#!/usr/bin/env bash
# Собирает подписанный apt-репозиторий («плоский», без дистрибутивов и компонентов)
# из пакетов .deb для публикации на GitHub Pages.
#   ./build-apt-repo.sh <каталог с .deb> <каталог сайта> [ID ключа GPG]
# Ключ должен быть импортирован в gpg; без ID берётся первый секретный ключ.
# Пользователь подключает репозиторий так:
#   deb [signed-by=/usr/share/keyrings/symo.gpg] https://olegegoism.github.io/SyMo ./
set -euo pipefail

DEB_DIR="${1:?каталог с .deb, например dist}"
SITE_DIR="${2:?каталог сайта, например site}"
KEY_ID="${3:-$(gpg --batch --list-secret-keys --with-colons | awk -F: '/^sec/ {print $5; exit}')}"

if [[ -z "$KEY_ID" ]]; then
    echo "❌ Нет секретного ключа GPG для подписи репозитория" >&2
    exit 1
fi
shopt -s nullglob
debs=("$DEB_DIR"/*.deb)
if ((${#debs[@]} == 0)); then
    echo "❌ В $DEB_DIR нет пакетов .deb" >&2
    exit 1
fi

rm -rf "$SITE_DIR"
mkdir -p "$SITE_DIR"
cp "${debs[@]}" "$SITE_DIR/"
cd "$SITE_DIR"

dpkg-scanpackages --multiversion . /dev/null > Packages 2>/dev/null
gzip -9kn Packages
# Release с контрольными суммами индексов: apt сверяет их с подписью InRelease.
{
    echo "Origin: SyMo"
    echo "Label: SyMo"
    echo "Suite: stable"
    echo "Description: SyMo system monitor"
    echo "Date: $(LC_ALL=C date -Ru)"
    for algo in MD5Sum:md5sum SHA256:sha256sum; do
        echo "${algo%%:*}:"
        for index in Packages Packages.gz; do
            printf ' %s %s %s\n' "$("${algo#*:}" "$index" | cut -d' ' -f1)" "$(stat -c%s "$index")" "$index"
        done
    done
} > Release
gpg --batch --yes --local-user "$KEY_ID" --clearsign --output InRelease Release
gpg --batch --yes --local-user "$KEY_ID" --armor --detach-sign --output Release.gpg Release
gpg --batch --yes --export "$KEY_ID" > symo.gpg
gpg --batch --yes --armor --export "$KEY_ID" > symo.asc

# Без Jekyll: Pages отдаёт файлы как есть.
touch .nojekyll

cat > index.html <<'HTML'
<!doctype html>
<meta charset="utf-8">
<title>SyMo apt repository</title>
<h1>SyMo apt repository</h1>
<pre>
sudo curl -fsSLo /usr/share/keyrings/symo.gpg https://olegegoism.github.io/SyMo/symo.gpg
echo "deb [signed-by=/usr/share/keyrings/symo.gpg] https://olegegoism.github.io/SyMo ./" | sudo tee /etc/apt/sources.list.d/symo.list
sudo apt update && sudo apt install symo
</pre>
<p><a href="https://github.com/OlegEgoism/SyMo">github.com/OlegEgoism/SyMo</a></p>
HTML

echo "✔ Репозиторий: $(pwd) (${#debs[@]} пакетов, ключ $KEY_ID)"
