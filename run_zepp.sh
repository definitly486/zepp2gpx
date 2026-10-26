#!/bin/sh
# Получает app_token через huami-token (если нужно) и запускает zepp2gpx.py.
#
# Использование:
#   ./run_zepp.sh                    # выгрузить в ./tracks (токен из кэша)
#   ./run_zepp.sh -r                 # принудительно получить новый токен
#   ./run_zepp.sh -o mydir --debug   # остальные аргументы уходят в zepp2gpx.py
#
# Переменные окружения:
#   ZEPP_EMAIL   email аккаунта Zepp (по умолчанию fg8989@gmail.com)
#   ZEPP_PASS    пароль; если не задан, будет запрошен без эха
#
# Требуется: huami-token в PATH, python3 и zepp2gpx.py рядом с этим файлом.

set -u

DIR=$(cd "$(dirname "$0")" && pwd)
EMAIL="${ZEPP_EMAIL:-fg8989@gmail.com}"
TOKEN_FILE="$HOME/.cache/zepp2gpx_token"
MIN_LEN=200

RELOGIN=0
if [ "${1:-}" = "-r" ]; then
    RELOGIN=1
    shift
fi

# Токен из окружения мешает кэшу, а zepp2gpx.py читает его первым
unset ZEPP_TOKEN

token_ok() {
    [ -s "$TOKEN_FILE" ] && [ "$(wc -c < "$TOKEN_FILE")" -gt "$MIN_LEN" ]
}

fetch_token() {
    command -v huami-token >/dev/null 2>&1 || {
        echo "Не найден huami-token в PATH." >&2
        exit 1
    }

    PASS="${ZEPP_PASS:-}"
    if [ -z "$PASS" ]; then
        printf 'Пароль Zepp для %s: ' "$EMAIL" >&2
        trap 'stty echo 2>/dev/null; rm -f "$TOKEN_FILE.log"; exit 130' INT TERM
        stty -echo 2>/dev/null
        read -r PASS
        stty echo 2>/dev/null
        printf '\n' >&2
    fi

    mkdir -p "$(dirname "$TOKEN_FILE")"
    umask 077
    LOG="$TOKEN_FILE.log"
    echo "Вхожу в Zepp, это может занять до минуты..." >&2
    # Лог содержит пароль и токены (DEBUG), поэтому не показываем и сразу удаляем
    # --no_logout: иначе сервер сразу инвалидирует выданный токен
    huami-token --method amazfit --email "$EMAIL" --password "$PASS" --no_logout \
        > "$LOG" 2>&1 &
    HPID=$!
    PASS=""
    while kill -0 "$HPID" 2>/dev/null; do
        printf '.' >&2
        sleep 2
    done
    wait "$HPID"
    printf '\n' >&2
    sed -n 's/^app_token=//p' "$LOG" > "$TOKEN_FILE.tmp"
    if grep -q "429\|Too Many" "$LOG"; then
        echo "Сервер ответил 429: подождите 30-60 минут." >&2
    fi
    rm -f "$LOG"

    if [ -s "$TOKEN_FILE.tmp" ] && [ "$(wc -c < "$TOKEN_FILE.tmp")" -gt "$MIN_LEN" ]; then
        mv "$TOKEN_FILE.tmp" "$TOKEN_FILE"
        chmod 600 "$TOKEN_FILE"
        echo "Токен получен ($(wc -c < "$TOKEN_FILE" | tr -d ' ') байт)." >&2
    else
        rm -f "$TOKEN_FILE.tmp"
        echo "Токен не получен: huami-token не вернул строку app_token=." >&2
        echo "Запустите huami-token вручную и посмотрите ошибку (HTTP 429: подождите час)." >&2
        exit 1
    fi
}

if [ "$RELOGIN" -eq 1 ] || ! token_ok; then
    fetch_token
else
    echo "Использую токен из $TOKEN_FILE (для нового: ./run_zepp.sh -r)." >&2
fi

# Если нет -o/--out в аргументах, пишем в ./tracks
case " $* " in
    *" -o "*|*" --out "*) python3 "$DIR/zepp2gpx.py" "$@" ;;
    *) python3 "$DIR/zepp2gpx.py" -o tracks "$@" ;;
esac