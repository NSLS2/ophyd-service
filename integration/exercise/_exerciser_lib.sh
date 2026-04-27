# Shared helpers for the bash exercisers.
#
# Source this from each exerciser:
#     . "$(dirname "$0")/_exerciser_lib.sh"
#
# Exposes: step, pass, fail, note, req, expect_status, expect_success.
# Writes the last response body to /tmp/exer_body for ad-hoc inspection.

if [ -t 1 ]; then
    GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; BOLD=''; RESET=''
fi

step() { printf "\n${BOLD}== %s ==${RESET}\n" "$1"; }
pass() { printf "  ${GREEN}PASS${RESET}  %s\n" "$1"; }
note() { printf "  ${YELLOW}NOTE${RESET}  %s\n" "$1"; }

# fail() honors a CLEANUP_FN env hook so callers (e.g. registry_roundtrip)
# can register their own teardown via `CLEANUP_FN=cleanup`.
fail() {
    printf "  ${RED}FAIL${RESET}  %s\n" "$1" >&2
    if [ -n "${CLEANUP_FN:-}" ] && declare -F "$CLEANUP_FN" >/dev/null; then
        "$CLEANUP_FN"
    fi
    exit 1
}

# req METHOD URL [BODY]  →  writes body to /tmp/exer_body, prints status
req() {
    local method=$1 url=$2 body="${3:-}"
    local -a args=(-s -o /tmp/exer_body -w "%{http_code}" -X "$method")
    if [ -n "$body" ]; then
        args+=(-H "Content-Type: application/json" -d "$body")
    fi
    curl "${args[@]}" "$url"
}

expect_status() {
    local want=$1 got=$2 url=$3
    if [ "$got" != "$want" ]; then
        printf "    response body: %s\n" "$(cat /tmp/exer_body 2>/dev/null | head -c 400)"
        fail "$url: expected HTTP $want, got $got"
    fi
}

# expect_success STATUS DESCRIPTION [EXPECTED_FALLBACK]
#   Accept any 2xx as PASS; otherwise fail with the explicit expected code.
#   EXPECTED_FALLBACK defaults to 200 — pass 201 / 204 / etc. when the
#   endpoint specifies a different success code.
expect_success() {
    local status=$1 description=$2 fallback="${3:-200}"
    case "$status" in
        20*) pass "$description  HTTP $status" ;;
        *)   expect_status "$fallback" "$status" "$description" ;;
    esac
}
